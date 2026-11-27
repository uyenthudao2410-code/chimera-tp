/*
 * Ultra-fast (< 2 ms) native Antigravity 2.0 lifecycle hook forwarder for Linux/POSIX.
 * Zero external dependencies: pure POSIX sockets with strict fail-open guarantees.
 *
 * Build: gcc -O2 -Wall -Wextra -o chimera-hook chimera_hook.c
 * Usage: chimera-hook <event_name>
 * Env:   CHIMERA_HOOK_URL (default: http://127.0.0.1:9780)
 */

#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_URL "http://127.0.0.1:9780"
#define MAX_STDIN_BYTES (2U * 1024U * 1024U)
#define MAX_RESPONSE_BYTES (4U * 1024U * 1024U)
#define DEFAULT_CONNECT_TIMEOUT_MS 200
#define DEFAULT_IO_TIMEOUT_MS 600

typedef struct {
    char host[256];
    char host_header[280];
    char base_path[256];
    uint16_t port;
} Endpoint;

static int64_t monotonic_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0;
    }
    return (int64_t)ts.tv_sec * 1000LL + (int64_t)(ts.tv_nsec / 1000000L);
}

static int env_timeout_ms(const char *name, int def_ms, int min_ms, int max_ms) {
    const char *v = getenv(name);
    if (!v || !*v) {
        return def_ms;
    }
    char *end = NULL;
    long parsed = strtol(v, &end, 10);
    if (end == v || parsed < min_ms) {
        return (parsed < min_ms && end != v) ? min_ms : def_ms;
    }
    if (parsed > max_ms) {
        return max_ms;
    }
    return (int)parsed;
}

static void sanitize_event(const char *raw, char *out, size_t out_cap) {
    size_t j = 0;
    if (raw) {
        for (size_t i = 0; raw[i] != '\0' && j + 1 < out_cap && j < 64; i++) {
            unsigned char c = (unsigned char)raw[i];
            if (isalnum(c) || c == '_' || c == '-') {
                out[j++] = (char)tolower(c);
            }
        }
    }
    if (j == 0) {
        snprintf(out, out_cap, "unknown");
    } else {
        out[j] = '\0';
    }
}

static bool parse_endpoint(const char *raw_url, Endpoint *ep) {
    memset(ep, 0, sizeof(*ep));
    if (!raw_url) {
        return false;
    }
    while (*raw_url && isspace((unsigned char)*raw_url)) {
        raw_url++;
    }
    if (*raw_url == '\0') {
        return false;
    }
    const char *rest = raw_url;
    if (strncmp(rest, "http://", 7) == 0) {
        rest += 7;
    } else if (strstr(rest, "://") != NULL) {
        return false;
    }

    const char *slash = strchr(rest, '/');
    size_t auth_len = slash ? (size_t)(slash - rest) : strlen(rest);
    while (auth_len > 0 && isspace((unsigned char)rest[auth_len - 1])) {
        auth_len--;
    }
    if (auth_len == 0 || auth_len >= sizeof(ep->host_header)) {
        return false;
    }
    memcpy(ep->host_header, rest, auth_len);
    ep->host_header[auth_len] = '\0';

    if (slash) {
        size_t plen = strlen(slash);
        while (plen > 0 && (slash[plen - 1] == '/' || isspace((unsigned char)slash[plen - 1]))) {
            plen--;
        }
        if (plen >= sizeof(ep->base_path)) {
            return false;
        }
        memcpy(ep->base_path, slash, plen);
        ep->base_path[plen] = '\0';
    }

    if (ep->host_header[0] == '[') {
        const char *close = strchr(ep->host_header, ']');
        if (!close) {
            return false;
        }
        size_t hlen = (size_t)(close - (ep->host_header + 1));
        if (hlen == 0 || hlen >= sizeof(ep->host)) {
            return false;
        }
        memcpy(ep->host, ep->host_header + 1, hlen);
        ep->host[hlen] = '\0';
        if (close[1] == ':') {
            char *end = NULL;
            long p = strtol(close + 2, &end, 10);
            if (end == close + 2 || *end != '\0' || p <= 0 || p > 65535) {
                return false;
            }
            ep->port = (uint16_t)p;
        } else if (close[1] == '\0') {
            ep->port = 80;
        } else {
            return false;
        }
    } else {
        const char *colon = strrchr(ep->host_header, ':');
        if (colon) {
            size_t hlen = (size_t)(colon - ep->host_header);
            if (hlen == 0 || hlen >= sizeof(ep->host)) {
                return false;
            }
            memcpy(ep->host, ep->host_header, hlen);
            ep->host[hlen] = '\0';
            char *end = NULL;
            long p = strtol(colon + 1, &end, 10);
            if (end == colon + 1 || *end != '\0' || p <= 0 || p > 65535) {
                return false;
            }
            ep->port = (uint16_t)p;
        } else {
            size_t hlen = strlen(ep->host_header);
            if (hlen == 0 || hlen >= sizeof(ep->host)) {
                return false;
            }
            memcpy(ep->host, ep->host_header, hlen + 1);
            ep->port = 80;
        }
    }
    return ep->port > 0;
}

static int connect_with_timeout(const Endpoint *ep, int timeout_ms) {
    struct sockaddr_storage ss;
    socklen_t slen = 0;
    int family = AF_UNSPEC;

    struct sockaddr_in sin4;
    memset(&sin4, 0, sizeof(sin4));
    if (inet_pton(AF_INET, ep->host, &sin4.sin_addr) == 1) {
        sin4.sin_family = AF_INET;
        sin4.sin_port = htons(ep->port);
        memcpy(&ss, &sin4, sizeof(sin4));
        slen = sizeof(sin4);
        family = AF_INET;
    } else {
        struct sockaddr_in6 sin6;
        memset(&sin6, 0, sizeof(sin6));
        if (inet_pton(AF_INET6, ep->host, &sin6.sin6_addr) == 1) {
            sin6.sin6_family = AF_INET6;
            sin6.sin6_port = htons(ep->port);
            memcpy(&ss, &sin6, sizeof(sin6));
            slen = sizeof(sin6);
            family = AF_INET6;
        } else {
            struct addrinfo hints;
            struct addrinfo *res = NULL;
            char port_str[16];
            memset(&hints, 0, sizeof(hints));
            hints.ai_socktype = SOCK_STREAM;
            hints.ai_family = AF_UNSPEC;
            snprintf(port_str, sizeof(port_str), "%u", (unsigned)ep->port);
            if (getaddrinfo(ep->host, port_str, &hints, &res) != 0 || !res) {
                return -1;
            }
            if (res->ai_addrlen > sizeof(ss)) {
                freeaddrinfo(res);
                return -1;
            }
            memcpy(&ss, res->ai_addr, res->ai_addrlen);
            slen = (socklen_t)res->ai_addrlen;
            family = res->ai_family;
            freeaddrinfo(res);
        }
    }

    int fd = socket(family, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }

    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) {
        close(fd);
        return -1;
    }

    int one = 1;
    (void)setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

    int rc = connect(fd, (const struct sockaddr *)&ss, slen);
    if (rc < 0) {
        if (errno != EINPROGRESS) {
            close(fd);
            return -1;
        }
        struct pollfd pfd;
        pfd.fd = fd;
        pfd.events = POLLOUT;
        pfd.revents = 0;
        int prc = poll(&pfd, 1, timeout_ms);
        if (prc <= 0) {
            close(fd);
            return -1;
        }
        int so_err = 0;
        socklen_t err_len = sizeof(so_err);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &so_err, &err_len) < 0 || so_err != 0) {
            close(fd);
            return -1;
        }
    }
    return fd;
}

static bool write_all_deadline(int fd, const uint8_t *buf, size_t len, int64_t deadline_ms) {
    size_t sent = 0;
    while (sent < len) {
        int64_t rem = deadline_ms - monotonic_ms();
        if (rem <= 0) {
            return false;
        }
        struct pollfd pfd = {fd, POLLOUT, 0};
        int prc = poll(&pfd, 1, (int)rem);
        if (prc <= 0) {
            if (prc < 0 && errno == EINTR) {
                continue;
            }
            return false;
        }
        ssize_t n = send(fd, buf + sent, len - sent, 0);
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) {
                continue;
            }
            return false;
        }
        if (n == 0) {
            return false;
        }
        sent += (size_t)n;
    }
    return true;
}

static bool ascii_ieq_n(const char *a, const char *b, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (tolower((unsigned char)a[i]) != tolower((unsigned char)b[i])) {
            return false;
        }
    }
    return true;
}

static bool ascii_contains_ci(const char *hay, size_t hay_len, const char *needle) {
    size_t nlen = strlen(needle);
    if (nlen == 0 || nlen > hay_len) {
        return false;
    }
    for (size_t i = 0; i + nlen <= hay_len; i++) {
        if (ascii_ieq_n(hay + i, needle, nlen)) {
            return true;
        }
    }
    return false;
}

static bool find_header_end(const uint8_t *buf, size_t len, size_t *hdr_end, size_t *body_start) {
    for (size_t i = 0; i + 3 < len; i++) {
        if (buf[i] == '\r' && buf[i + 1] == '\n' && buf[i + 2] == '\r' && buf[i + 3] == '\n') {
            *hdr_end = i;
            *body_start = i + 4;
            return true;
        }
    }
    for (size_t i = 0; i + 1 < len; i++) {
        if (buf[i] == '\n' && buf[i + 1] == '\n') {
            *hdr_end = i;
            *body_start = i + 2;
            return true;
        }
    }
    return false;
}

static int parse_status_code(const uint8_t *hdr, size_t hdr_len) {
    if (hdr_len < 12 || memcmp(hdr, "HTTP/1.", 7) != 0) {
        return -1;
    }
    size_t i = 0;
    while (i < hdr_len && hdr[i] != ' ' && hdr[i] != '\r' && hdr[i] != '\n') {
        i++;
    }
    while (i < hdr_len && hdr[i] == ' ') {
        i++;
    }
    if (i + 3 > hdr_len || !isdigit(hdr[i]) || !isdigit(hdr[i + 1]) || !isdigit(hdr[i + 2])) {
        return -1;
    }
    return (hdr[i] - '0') * 100 + (hdr[i + 1] - '0') * 10 + (hdr[i + 2] - '0');
}

static void parse_headers(const uint8_t *hdr, size_t hdr_len, bool *has_cl, size_t *cl, bool *chunked) {
    *has_cl = false;
    *cl = 0;
    *chunked = false;

    size_t pos = 0;
    while (pos < hdr_len && hdr[pos] != '\n') {
        pos++;
    }
    if (pos < hdr_len) {
        pos++;
    }
    while (pos < hdr_len) {
        size_t line_start = pos;
        while (pos < hdr_len && hdr[pos] != '\n') {
            pos++;
        }
        size_t line_end = pos;
        if (pos < hdr_len) {
            pos++;
        }
        if (line_end > line_start && hdr[line_end - 1] == '\r') {
            line_end--;
        }
        const char *line = (const char *)(hdr + line_start);
        size_t line_len = line_end - line_start;
        const char *colon = memchr(line, ':', line_len);
        if (!colon) {
            continue;
        }
        size_t klen = (size_t)(colon - line);
        const char *val = colon + 1;
        size_t vlen = line_len - klen - 1;
        while (vlen > 0 && (*val == ' ' || *val == '\t')) {
            val++;
            vlen--;
        }
        if (klen == 14 && ascii_ieq_n(line, "content-length", 14)) {
            char tmp[32];
            if (vlen < sizeof(tmp)) {
                memcpy(tmp, val, vlen);
                tmp[vlen] = '\0';
                char *end = NULL;
                unsigned long n = strtoul(tmp, &end, 10);
                if (end != tmp) {
                    *has_cl = true;
                    *cl = (size_t)n;
                }
            }
        } else if (klen == 17 && ascii_ieq_n(line, "transfer-encoding", 17)) {
            if (ascii_contains_ci(val, vlen, "chunked")) {
                *chunked = true;
            }
        }
    }
}

static bool decode_chunked(const uint8_t *raw, size_t raw_len, uint8_t **out_buf, size_t *out_len) {
    uint8_t *out = malloc(raw_len + 1);
    if (!out) {
        return false;
    }
    size_t pos = 0;
    size_t written = 0;
    while (pos < raw_len) {
        size_t line_end = pos;
        while (line_end + 1 < raw_len && !(raw[line_end] == '\r' && raw[line_end + 1] == '\n')) {
            line_end++;
        }
        if (line_end + 1 >= raw_len) {
            free(out);
            return false;
        }
        char hex_buf[32];
        size_t hlen = line_end - pos;
        if (hlen == 0 || hlen >= sizeof(hex_buf)) {
            free(out);
            return false;
        }
        memcpy(hex_buf, raw + pos, hlen);
        hex_buf[hlen] = '\0';
        char *semi = strchr(hex_buf, ';');
        if (semi) {
            *semi = '\0';
        }
        char *end = NULL;
        unsigned long chunk_size = strtoul(hex_buf, &end, 16);
        if (end == hex_buf) {
            free(out);
            return false;
        }
        pos = line_end + 2;
        if (chunk_size == 0) {
            out[written] = '\0';
            *out_buf = out;
            *out_len = written;
            return true;
        }
        if (pos + chunk_size + 2 > raw_len || written + chunk_size > MAX_RESPONSE_BYTES) {
            free(out);
            return false;
        }
        memcpy(out + written, raw + pos, chunk_size);
        written += chunk_size;
        pos += chunk_size;
        if (raw[pos] != '\r' || raw[pos + 1] != '\n') {
            free(out);
            return false;
        }
        pos += 2;
    }
    free(out);
    return false;
}

/* Minimal strict JSON object validator */
typedef struct {
    const uint8_t *b;
    size_t len;
    size_t i;
} JsonCheck;

static void jc_skip_ws(JsonCheck *jc) {
    while (jc->i < jc->len && (jc->b[jc->i] == ' ' || jc->b[jc->i] == '\t' ||
                               jc->b[jc->i] == '\r' || jc->b[jc->i] == '\n')) {
        jc->i++;
    }
}

static bool jc_string(JsonCheck *jc) {
    if (jc->i >= jc->len || jc->b[jc->i] != '"') {
        return false;
    }
    jc->i++;
    while (jc->i < jc->len) {
        uint8_t c = jc->b[jc->i++];
        if (c == '"') {
            return true;
        }
        if (c < 0x20) {
            return false;
        }
        if (c == '\\') {
            if (jc->i >= jc->len) {
                return false;
            }
            uint8_t esc = jc->b[jc->i++];
            switch (esc) {
                case '"': case '\\': case '/': case 'b':
                case 'f': case 'n': case 'r': case 't':
                    break;
                case 'u':
                    if (jc->i + 4 > jc->len) {
                        return false;
                    }
                    for (int k = 0; k < 4; k++) {
                        if (!isxdigit(jc->b[jc->i + (size_t)k])) {
                            return false;
                        }
                    }
                    jc->i += 4;
                    break;
                default:
                    return false;
            }
        }
    }
    return false;
}

static bool jc_number(JsonCheck *jc) {
    if (jc->i < jc->len && jc->b[jc->i] == '-') {
        jc->i++;
    }
    if (jc->i >= jc->len) {
        return false;
    }
    if (jc->b[jc->i] == '0') {
        jc->i++;
    } else if (isdigit(jc->b[jc->i])) {
        while (jc->i < jc->len && isdigit(jc->b[jc->i])) {
            jc->i++;
        }
    } else {
        return false;
    }
    if (jc->i < jc->len && jc->b[jc->i] == '.') {
        jc->i++;
        if (jc->i >= jc->len || !isdigit(jc->b[jc->i])) {
            return false;
        }
        while (jc->i < jc->len && isdigit(jc->b[jc->i])) {
            jc->i++;
        }
    }
    if (jc->i < jc->len && (jc->b[jc->i] == 'e' || jc->b[jc->i] == 'E')) {
        jc->i++;
        if (jc->i < jc->len && (jc->b[jc->i] == '+' || jc->b[jc->i] == '-')) {
            jc->i++;
        }
        if (jc->i >= jc->len || !isdigit(jc->b[jc->i])) {
            return false;
        }
        while (jc->i < jc->len && isdigit(jc->b[jc->i])) {
            jc->i++;
        }
    }
    return true;
}

static bool jc_object(JsonCheck *jc, int depth);
static bool jc_array(JsonCheck *jc, int depth);

static bool jc_value(JsonCheck *jc, int depth) {
    if (depth > 64) {
        return false;
    }
    jc_skip_ws(jc);
    if (jc->i >= jc->len) {
        return false;
    }
    uint8_t c = jc->b[jc->i];
    if (c == '{') return jc_object(jc, depth + 1);
    if (c == '[') return jc_array(jc, depth + 1);
    if (c == '"') return jc_string(jc);
    if (c == 't' && jc->i + 4 <= jc->len && memcmp(jc->b + jc->i, "true", 4) == 0) {
        jc->i += 4;
        return true;
    }
    if (c == 'f' && jc->i + 5 <= jc->len && memcmp(jc->b + jc->i, "false", 5) == 0) {
        jc->i += 5;
        return true;
    }
    if (c == 'n' && jc->i + 4 <= jc->len && memcmp(jc->b + jc->i, "null", 4) == 0) {
        jc->i += 4;
        return true;
    }
    if (c == '-' || isdigit(c)) return jc_number(jc);
    return false;
}

static bool jc_array(JsonCheck *jc, int depth) {
    if (jc->i >= jc->len || jc->b[jc->i] != '[') {
        return false;
    }
    jc->i++;
    jc_skip_ws(jc);
    if (jc->i < jc->len && jc->b[jc->i] == ']') {
        jc->i++;
        return true;
    }
    for (;;) {
        if (!jc_value(jc, depth)) {
            return false;
        }
        jc_skip_ws(jc);
        if (jc->i >= jc->len) {
            return false;
        }
        if (jc->b[jc->i] == ',') {
            jc->i++;
        } else if (jc->b[jc->i] == ']') {
            jc->i++;
            return true;
        } else {
            return false;
        }
    }
}

static bool jc_object(JsonCheck *jc, int depth) {
    if (jc->i >= jc->len || jc->b[jc->i] != '{') {
        return false;
    }
    jc->i++;
    jc_skip_ws(jc);
    if (jc->i < jc->len && jc->b[jc->i] == '}') {
        jc->i++;
        return true;
    }
    for (;;) {
        jc_skip_ws(jc);
        if (!jc_string(jc)) {
            return false;
        }
        jc_skip_ws(jc);
        if (jc->i >= jc->len || jc->b[jc->i] != ':') {
            return false;
        }
        jc->i++;
        if (!jc_value(jc, depth)) {
            return false;
        }
        jc_skip_ws(jc);
        if (jc->i >= jc->len) {
            return false;
        }
        if (jc->b[jc->i] == ',') {
            jc->i++;
        } else if (jc->b[jc->i] == '}') {
            jc->i++;
            return true;
        } else {
            return false;
        }
    }
}

static bool is_valid_json_object(const uint8_t *buf, size_t len) {
    JsonCheck jc = {buf, len, 0};
    jc_skip_ws(&jc);
    if (!jc_object(&jc, 0)) {
        return false;
    }
    jc_skip_ws(&jc);
    return jc.i == len;
}

static uint8_t *read_stdin_capped(size_t *out_len) {
    size_t cap = 4096;
    size_t len = 0;
    uint8_t *buf = malloc(cap);
    if (!buf) {
        *out_len = 0;
        return NULL;
    }
    while (len < MAX_STDIN_BYTES) {
        if (len == cap) {
            size_t next_cap = cap * 2;
            if (next_cap > MAX_STDIN_BYTES) {
                next_cap = MAX_STDIN_BYTES;
            }
            uint8_t *nb = realloc(buf, next_cap);
            if (!nb) {
                break;
            }
            buf = nb;
            cap = next_cap;
        }
        size_t want = cap - len;
        if (want > MAX_STDIN_BYTES - len) {
            want = MAX_STDIN_BYTES - len;
        }
        ssize_t n = read(STDIN_FILENO, buf + len, want);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            break;
        }
        if (n == 0) {
            break;
        }
        len += (size_t)n;
    }
    *out_len = len;
    return buf;
}

static void emit_fail_open(const char *event) {
    if (strcmp(event, "pre_tool_use") == 0) {
        fputs("{\"decision\":\"allow\"}\n", stdout);
    } else {
        fputs("{}\n", stdout);
    }
    fflush(stdout);
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);

    char event[72];
    sanitize_event(argc > 1 ? argv[1] : "unknown", event, sizeof(event));

    size_t stdin_len = 0;
    uint8_t *stdin_buf = read_stdin_capped(&stdin_len);

    const char *url = getenv("CHIMERA_HOOK_URL");
    if (!url || !*url) {
        url = DEFAULT_URL;
    }

    Endpoint ep;
    if (!parse_endpoint(url, &ep)) {
        free(stdin_buf);
        emit_fail_open(event);
        return 0;
    }

    int connect_ms = env_timeout_ms("CHIMERA_HOOK_CONNECT_TIMEOUT_MS", DEFAULT_CONNECT_TIMEOUT_MS, 20, 5000);
    int io_ms = env_timeout_ms("CHIMERA_HOOK_IO_TIMEOUT_MS", DEFAULT_IO_TIMEOUT_MS, 50, 5000);

    int fd = connect_with_timeout(&ep, connect_ms);
    if (fd < 0) {
        free(stdin_buf);
        emit_fail_open(event);
        return 0;
    }

    const uint8_t *payload = (stdin_buf && stdin_len > 0) ? stdin_buf : (const uint8_t *)"{}";
    size_t payload_len = (stdin_buf && stdin_len > 0) ? stdin_len : 2;

    char hdr[1024];
    int hdr_len = snprintf(
        hdr, sizeof(hdr),
        "POST %s/v1/hook/%s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n"
        "User-Agent: chimera-hook/1.0\r\n"
        "\r\n",
        ep.base_path, event, ep.host_header, payload_len);
    if (hdr_len <= 0 || (size_t)hdr_len >= sizeof(hdr)) {
        close(fd);
        free(stdin_buf);
        emit_fail_open(event);
        return 0;
    }

    size_t req_len = (size_t)hdr_len + payload_len;
    uint8_t *req = malloc(req_len);
    if (!req) {
        close(fd);
        free(stdin_buf);
        emit_fail_open(event);
        return 0;
    }
    memcpy(req, hdr, (size_t)hdr_len);
    memcpy(req + hdr_len, payload, payload_len);

    int64_t deadline = monotonic_ms() + io_ms;
    bool sent_ok = write_all_deadline(fd, req, req_len, deadline);
    free(req);
    free(stdin_buf);
    if (!sent_ok) {
        close(fd);
        emit_fail_open(event);
        return 0;
    }

    size_t resp_cap = 4096;
    size_t resp_len = 0;
    uint8_t *resp = malloc(resp_cap);
    if (!resp) {
        close(fd);
        emit_fail_open(event);
        return 0;
    }

    bool got_headers = false;
    size_t hdr_end = 0;
    size_t body_start = 0;
    bool has_cl = false;
    size_t cl = 0;
    bool is_chunked = false;
    bool read_ok = true;

    for (;;) {
        int64_t rem = deadline - monotonic_ms();
        if (rem <= 0) {
            read_ok = false;
            break;
        }
        struct pollfd pfd = {fd, POLLIN, 0};
        int prc = poll(&pfd, 1, (int)rem);
        if (prc <= 0) {
            if (prc < 0 && errno == EINTR) {
                continue;
            }
            read_ok = false;
            break;
        }
        if (resp_len + 4096 > resp_cap) {
            size_t next_cap = resp_cap * 2;
            if (next_cap > MAX_RESPONSE_BYTES) {
                next_cap = MAX_RESPONSE_BYTES;
            }
            if (next_cap <= resp_len) {
                read_ok = false;
                break;
            }
            uint8_t *nr = realloc(resp, next_cap);
            if (!nr) {
                read_ok = false;
                break;
            }
            resp = nr;
            resp_cap = next_cap;
        }
        ssize_t n = recv(fd, resp + resp_len, resp_cap - resp_len, 0);
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) {
                continue;
            }
            read_ok = false;
            break;
        }
        if (n == 0) {
            break;
        }
        resp_len += (size_t)n;
        if (!got_headers && find_header_end(resp, resp_len, &hdr_end, &body_start)) {
            if (parse_status_code(resp, hdr_end) != 200) {
                read_ok = false;
                break;
            }
            parse_headers(resp, hdr_end, &has_cl, &cl, &is_chunked);
            got_headers = true;
        }
        if (got_headers && has_cl && !is_chunked && resp_len >= body_start + cl) {
            break;
        }
    }
    close(fd);

    if (!read_ok || !got_headers) {
        free(resp);
        emit_fail_open(event);
        return 0;
    }

    const uint8_t *raw_body = resp + body_start;
    size_t raw_body_len = resp_len - body_start;
    uint8_t *decoded = NULL;
    const uint8_t *body = raw_body;
    size_t body_len = raw_body_len;

    if (is_chunked) {
        if (!decode_chunked(raw_body, raw_body_len, &decoded, &body_len)) {
            free(resp);
            emit_fail_open(event);
            return 0;
        }
        body = decoded;
    } else if (has_cl) {
        if (raw_body_len < cl) {
            free(resp);
            emit_fail_open(event);
            return 0;
        }
        body_len = cl;
    }

    while (body_len > 0 && (*body == ' ' || *body == '\t' || *body == '\r' || *body == '\n')) {
        body++;
        body_len--;
    }
    while (body_len > 0 && (body[body_len - 1] == ' ' || body[body_len - 1] == '\t' ||
                            body[body_len - 1] == '\r' || body[body_len - 1] == '\n')) {
        body_len--;
    }

    if (body_len == 0 || !is_valid_json_object(body, body_len)) {
        free(decoded);
        free(resp);
        emit_fail_open(event);
        return 0;
    }

    (void)fwrite(body, 1, body_len, stdout);
    fputc('\n', stdout);
    fflush(stdout);

    free(decoded);
    free(resp);
    return 0;
}
