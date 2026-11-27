/*
 * CHIMERA-MICRONUCLEUS (Linux POSIX C11 Native Spine)
 * Zero external dependencies — compiles with `gcc -O2 -pthread -Wall -Wextra -o chimera_spine chimera_spine.c`.
 * Targets ~1.5-4 MiB VmRSS on svhome (vs ~58-60 MiB Python daemon = -93% RAM!) while keeping
 * Python Organ workers ephemeral (0.00 MiB when sleeping, woken on demand for complex routes).
 */
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define MAX_GHOST_SLOTS 64
#define MAX_GHOST_FILE  (256 * 1024)

typedef struct {
    char path[512];
    long mtime_sec;
    long mtime_nsec;
    size_t size;
    char *data;
    int used;
} GhostSlot;

static int g_port = 9795;
static int g_organ_port = 0;
static int g_idle_secs = 60;
static char g_nixl_path[512] = "/dev/shm/chimera_nixl_ring.bin";
static char **g_organ_argv = NULL;
static volatile sig_atomic_t g_shutdown = 0;
static time_t g_started_at = 0;

static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static pid_t g_organ_pid = -1;
static time_t g_organ_last_used = 0;
static uint64_t g_organ_wakes = 0;
static uint64_t g_organ_sleeps = 0;
static double g_last_wake_ms = 0.0;
static uint64_t g_req_native = 0;
static uint64_t g_req_proxied = 0;

static GhostSlot g_ghost[MAX_GHOST_SLOTS];
static uint64_t g_ghost_hits = 0;
static uint64_t g_ghost_misses = 0;
static uint64_t g_ghost_saved = 0;
static int g_ghost_cursor = 0;

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1000.0 + (double)ts.tv_nsec / 1e6;
}

static void read_proc_rss_mib(double *rss_mib, double *hwm_mib) {
    *rss_mib = 0.0;
    *hwm_mib = 0.0;
    FILE *f = fopen("/proc/self/status", "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        long kb = 0;
        if (strncmp(line, "VmRSS:", 6) == 0 && sscanf(line + 6, "%ld", &kb) == 1) {
            *rss_mib = (double)kb / 1024.0;
        } else if (strncmp(line, "VmHWM:", 6) == 0 && sscanf(line + 6, "%ld", &kb) == 1) {
            *hwm_mib = (double)kb / 1024.0;
        }
    }
    fclose(f);
}

static void read_host_telemetry(double *load1, double *mem_avail_gb) {
    *load1 = 0.0;
    *mem_avail_gb = 0.0;
    FILE *fl = fopen("/proc/loadavg", "r");
    if (fl) {
        (void)fscanf(fl, "%lf", load1);
        fclose(fl);
    }
    FILE *fm = fopen("/proc/meminfo", "r");
    if (fm) {
        char line[256];
        while (fgets(line, sizeof(line), fm)) {
            long kb = 0;
            if (strncmp(line, "MemAvailable:", 13) == 0 && sscanf(line + 13, "%ld", &kb) == 1) {
                *mem_avail_gb = (double)kb / 1048576.0;
                break;
            }
        }
        fclose(fm);
    }
}

static int organ_is_awake_locked(void) {
    if (g_organ_pid <= 0) return 0;
    int st = 0;
    pid_t r = waitpid(g_organ_pid, &st, WNOHANG);
    if (r == g_organ_pid || (r < 0 && errno == ECHILD)) {
        g_organ_pid = -1;
        return 0;
    }
    return 1;
}

static int organ_sleep_locked(void) {
    if (g_organ_pid <= 0) return 0;
    kill(g_organ_pid, SIGTERM);
    for (int i = 0; i < 20; i++) {
        int st = 0;
        if (waitpid(g_organ_pid, &st, WNOHANG) == g_organ_pid) {
            g_organ_pid = -1;
            g_organ_sleeps++;
            return 1;
        }
        usleep(25000);
    }
    kill(g_organ_pid, SIGKILL);
    waitpid(g_organ_pid, NULL, 0);
    g_organ_pid = -1;
    g_organ_sleeps++;
    return 1;
}

static int connect_local(int port, int timeout_ms) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)port);
    inet_pton(AF_INET, "127.0.0.1", &sa.sin_addr);
    if (connect(fd, (struct sockaddr *)&sa, sizeof(sa)) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static int organ_ensure_awake_locked(void) {
    g_organ_last_used = time(NULL);
    if (organ_is_awake_locked()) return 1;
    if (!g_organ_argv || !g_organ_argv[0] || g_organ_port <= 0) return 0;
    double t0 = now_ms();
    pid_t pid = fork();
    if (pid < 0) return 0;
    if (pid == 0) {
        int devnull = open("/dev/null", O_RDWR);
        if (devnull >= 0) {
            dup2(devnull, STDIN_FILENO);
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            if (devnull > 2) close(devnull);
        }
        execvp(g_organ_argv[0], g_organ_argv);
        _exit(127);
    }
    g_organ_pid = pid;
    for (int i = 0; i < 160; i++) {
        int s = connect_local(g_organ_port, 120);
        if (s >= 0) {
            close(s);
            g_organ_wakes++;
            g_last_wake_ms = now_ms() - t0;
            g_organ_last_used = time(NULL);
            return 1;
        }
        usleep(40000);
    }
    organ_sleep_locked();
    return 0;
}

static void *reaper_thread(void *arg) {
    (void)arg;
    while (!g_shutdown) {
        usleep(500000);
        pthread_mutex_lock(&g_mu);
        if (organ_is_awake_locked() && (time(NULL) - g_organ_last_used) >= g_idle_secs) {
            organ_sleep_locked();
        }
        pthread_mutex_unlock(&g_mu);
    }
    return NULL;
}

static void send_http(int fd, int status, const char *reason, const char *body) {
    size_t blen = strlen(body);
    char hdr[512];
    int hlen = snprintf(
        hdr, sizeof(hdr),
        "HTTP/1.1 %d %s\r\nContent-Type: application/json\r\nContent-Length: %zu\r\n"
        "Connection: close\r\nX-Chimera-Engine: micronucleus-c11\r\n\r\n",
        status, reason, blen
    );
    if (hlen > 0) (void)write(fd, hdr, (size_t)hlen);
    if (blen > 0) (void)write(fd, body, blen);
}

static void url_decode_into(const char *src, char *dst, size_t max_len) {
    size_t j = 0;
    for (size_t i = 0; src[i] && src[i] != '&' && src[i] != ' ' && j + 1 < max_len; i++) {
        if (src[i] == '%' && src[i + 1] && src[i + 2]) {
            char hex[3] = { src[i + 1], src[i + 2], 0 };
            dst[j++] = (char)strtol(hex, NULL, 16);
            i += 2;
        } else if (src[i] == '+') {
            dst[j++] = ' ';
        } else {
            dst[j++] = src[i];
        }
    }
    dst[j] = '\0';
}

static void handle_nixl_hormones(int fd) {
    uint8_t buf[64];
    FILE *f = fopen(g_nixl_path, "rb");
    if (!f || fread(buf, 1, 64, f) < 64) {
        if (f) fclose(f);
        send_http(fd, 200, "OK", "{\"ok\":false,\"error\":\"nixl_ring_unavailable\"}");
        return;
    }
    fclose(f);
    char magic[5] = { (char)buf[32], (char)buf[33], (char)buf[34], (char)buf[35], 0 };
    uint16_t seq = (uint16_t)buf[36] | ((uint16_t)buf[37] << 8);
    uint16_t crc = (uint16_t)buf[38] | ((uint16_t)buf[39] << 8);
    float v[6];
    memcpy(v, buf + 40, sizeof(v));
    char out[512];
    snprintf(
        out, sizeof(out),
        "{\"ok\":true,\"source\":\"native_c11_64b_ring\",\"magic\":\"%s\",\"seq\":%u,\"crc16\":%u,"
        "\"hormones\":{\"adrenaline\":%.4f,\"cortisol\":%.4f,\"dopamine\":%.4f,"
        "\"melatonin\":%.4f,\"cytokine\":%.4f,\"oxytocin\":%.4f}}",
        magic, seq, crc, v[0], v[1], v[2], v[3], v[4], v[5]
    );
    send_http(fd, 200, "OK", out);
}

static void handle_ghost_get(int fd, const char *query) {
    const char *p = strstr(query, "path=");
    if (!p) {
        send_http(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"path_required\"}");
        return;
    }
    char path[512];
    url_decode_into(p + 5, path, sizeof(path));
    struct stat st;
    if (stat(path, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size > MAX_GHOST_FILE) {
        send_http(fd, 404, "Not Found", "{\"ok\":false,\"error\":\"file_not_found\"}");
        return;
    }
    int hit = 0;
    size_t sz = (size_t)st.st_size;
    pthread_mutex_lock(&g_mu);
    for (int i = 0; i < MAX_GHOST_SLOTS; i++) {
        if (g_ghost[i].used && strcmp(g_ghost[i].path, path) == 0 &&
            g_ghost[i].mtime_sec == st.st_mtim.tv_sec &&
            g_ghost[i].mtime_nsec == st.st_mtim.tv_nsec &&
            g_ghost[i].size == sz) {
            hit = 1;
            g_ghost_hits++;
            g_ghost_saved += sz;
            break;
        }
    }
    if (!hit) {
        g_ghost_misses++;
        FILE *f = fopen(path, "rb");
        if (f) {
            char *mem = (char *)malloc(sz + 1);
            if (mem) {
                size_t rd = fread(mem, 1, sz, f);
                mem[rd] = '\0';
                GhostSlot *slot = &g_ghost[g_ghost_cursor % MAX_GHOST_SLOTS];
                g_ghost_cursor++;
                free(slot->data);
                strncpy(slot->path, path, sizeof(slot->path) - 1);
                slot->path[sizeof(slot->path) - 1] = '\0';
                slot->mtime_sec = st.st_mtim.tv_sec;
                slot->mtime_nsec = st.st_mtim.tv_nsec;
                slot->size = rd;
                slot->data = mem;
                slot->used = 1;
            }
            fclose(f);
        }
    }
    pthread_mutex_unlock(&g_mu);
    char out[256];
    snprintf(out, sizeof(out), "{\"ok\":true,\"hit\":%s,\"bytes\":%zu}", hit ? "true" : "false", sz);
    send_http(fd, 200, "OK", out);
}

static void *client_thread(void *arg) {
    int fd = *(int *)arg;
    free(arg);
    struct timeval tv = { 4, 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    char buf[32768];
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    if (n <= 0) {
        close(fd);
        return NULL;
    }
    buf[n] = '\0';
    char method[16] = {0}, target[1024] = {0};
    if (sscanf(buf, "%15s %1023s", method, target) < 2) {
        close(fd);
        return NULL;
    }
    char *qmark = strchr(target, '?');
    const char *query = "";
    if (qmark) {
        *qmark = '\0';
        query = qmark + 1;
    }

    if (strcmp(method, "GET") == 0 && (strcmp(target, "/healthz") == 0 || strcmp(target, "/v1/spine/status") == 0)) {
        double rss = 0.0, hwm = 0.0;
        read_proc_rss_mib(&rss, &hwm);
        pthread_mutex_lock(&g_mu);
        g_req_native++;
        int aw = organ_is_awake_locked();
        uint64_t wakes = g_organ_wakes, sleeps = g_organ_sleeps;
        double lw = g_last_wake_ms;
        uint64_t rn = g_req_native, rp = g_req_proxied;
        uint64_t gh = g_ghost_hits, gm = g_ghost_misses, gs = g_ghost_saved;
        int entries = 0;
        for (int i = 0; i < MAX_GHOST_SLOTS; i++) entries += g_ghost[i].used;
        pthread_mutex_unlock(&g_mu);
        char out[1024];
        snprintf(
            out, sizeof(out),
            "{\"ok\":true,\"engine\":\"chimera-micronucleus-c11\",\"pid\":%d,\"port\":%d,"
            "\"rss_mib\":%.3f,\"hwm_mib\":%.3f,\"uptime_s\":%ld,"
            "\"python_organ_state\":\"%s\",\"python_organ_port\":%d,"
            "\"python_organ_rss_when_sleeping_mib\":0.0,"
            "\"organ_wakes\":%llu,\"organ_sleeps\":%llu,\"last_wake_ms\":%.2f,"
            "\"requests_native\":%llu,\"requests_proxied\":%llu,"
            "\"ghost_ring\":{\"entries\":%d,\"hits\":%llu,\"misses\":%llu,\"bytes_saved\":%llu}}",
            (int)getpid(), g_port, rss, hwm, (long)(time(NULL) - g_started_at),
            aw ? "awake" : "sleeping_0_bytes", g_organ_port,
            (unsigned long long)wakes, (unsigned long long)sleeps, lw,
            (unsigned long long)rn, (unsigned long long)rp,
            entries, (unsigned long long)gh, (unsigned long long)gm, (unsigned long long)gs
        );
        send_http(fd, 200, "OK", out);
        close(fd);
        return NULL;
    }

    if (strcmp(method, "GET") == 0 && strcmp(target, "/.well-known/chimera.json") == 0) {
        double rss = 0.0, hwm = 0.0;
        read_proc_rss_mib(&rss, &hwm);
        pthread_mutex_lock(&g_mu);
        g_req_native++;
        pthread_mutex_unlock(&g_mu);
        char out[384];
        snprintf(
            out, sizeof(out),
            "{\"ok\":true,\"schema\":\"chimera.capabilities.v1\",\"engine\":\"chimera-micronucleus-c11\","
            "\"pid\":%d,\"rss_mib\":%.3f,\"port\":%d,\"hot_path_python_loaded\":false}",
            (int)getpid(), rss, g_port
        );
        send_http(fd, 200, "OK", out);
        close(fd);
        return NULL;
    }

    if (strcmp(method, "GET") == 0 && strcmp(target, "/v1/nixl/hormones") == 0) {
        pthread_mutex_lock(&g_mu);
        g_req_native++;
        pthread_mutex_unlock(&g_mu);
        handle_nixl_hormones(fd);
        close(fd);
        return NULL;
    }

    if (strcmp(method, "GET") == 0 && strcmp(target, "/v1/peer/telemetry") == 0) {
        double rss = 0.0, hwm = 0.0, load1 = 0.0, mem_gb = 0.0;
        read_proc_rss_mib(&rss, &hwm);
        read_host_telemetry(&load1, &mem_gb);
        pthread_mutex_lock(&g_mu);
        g_req_native++;
        pthread_mutex_unlock(&g_mu);
        char out[512];
        snprintf(
            out, sizeof(out),
            "{\"ok\":true,\"engine\":\"chimera-micronucleus-c11\",\"pid\":%d,"
            "\"rss_mib\":%.3f,\"hwm_mib\":%.3f,\"load_1m\":%.2f,\"mem_avail_gb\":%.2f,"
            "\"zero_python_hot_path\":true}",
            (int)getpid(), rss, hwm, load1, mem_gb
        );
        send_http(fd, 200, "OK", out);
        close(fd);
        return NULL;
    }

    if (strcmp(method, "GET") == 0 && strcmp(target, "/v1/ghost/get") == 0) {
        pthread_mutex_lock(&g_mu);
        g_req_native++;
        pthread_mutex_unlock(&g_mu);
        handle_ghost_get(fd, query);
        close(fd);
        return NULL;
    }

    if (strcmp(method, "POST") == 0 && strcmp(target, "/v1/spine/sleep-organ") == 0) {
        pthread_mutex_lock(&g_mu);
        g_req_native++;
        int slept = organ_sleep_locked();
        pthread_mutex_unlock(&g_mu);
        char out[128];
        snprintf(out, sizeof(out), "{\"ok\":true,\"slept\":%s,\"python_organ_state\":\"sleeping_0_bytes\"}", slept ? "true" : "false");
        send_http(fd, 200, "OK", out);
        close(fd);
        return NULL;
    }

    if (strcmp(method, "POST") == 0 && strcmp(target, "/v1/spine/shutdown") == 0) {
        pthread_mutex_lock(&g_mu);
        g_req_native++;
        organ_sleep_locked();
        g_shutdown = 1;
        pthread_mutex_unlock(&g_mu);
        send_http(fd, 200, "OK", "{\"ok\":true,\"shutting_down\":true}");
        close(fd);
        return NULL;
    }

    /* Complex route -> wake ephemeral Python organ & proxy */
    pthread_mutex_lock(&g_mu);
    int awake = organ_ensure_awake_locked();
    int oport = g_organ_port;
    pthread_mutex_unlock(&g_mu);
    if (!awake) {
        send_http(fd, 503, "Service Unavailable", "{\"ok\":false,\"error\":\"ephemeral_organ_unavailable\"}");
        close(fd);
        return NULL;
    }
    int up = connect_local(oport, 4000);
    if (up < 0) {
        send_http(fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"organ_connect_failed\"}");
        close(fd);
        return NULL;
    }
    (void)write(up, buf, (size_t)n);
    shutdown(up, SHUT_WR);
    char rbuf[16384];
    ssize_t rn;
    while ((rn = read(up, rbuf, sizeof(rbuf))) > 0) {
        (void)write(fd, rbuf, (size_t)rn);
    }
    close(up);
    pthread_mutex_lock(&g_mu);
    g_req_proxied++;
    pthread_mutex_unlock(&g_mu);
    close(fd);
    return NULL;
}

static void on_sig(int sig) {
    (void)sig;
    g_shutdown = 1;
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    signal(SIGTERM, on_sig);
    signal(SIGINT, on_sig);
    g_started_at = time(NULL);

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
            g_port = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--organ-port") == 0 && i + 1 < argc) {
            g_organ_port = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--idle-secs") == 0 && i + 1 < argc) {
            g_idle_secs = atoi(argv[++i]);
            if (g_idle_secs < 1) g_idle_secs = 1;
        } else if (strcmp(argv[i], "--nixl-path") == 0 && i + 1 < argc) {
            strncpy(g_nixl_path, argv[++i], sizeof(g_nixl_path) - 1);
        } else if (strcmp(argv[i], "--organ-cmd") == 0 && i + 1 < argc) {
            g_organ_argv = &argv[i + 1];
            break;
        }
    }

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) return 1;
    int one = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)g_port);
    inet_pton(AF_INET, "127.0.0.1", &sa.sin_addr);
    if (bind(srv, (struct sockaddr *)&sa, sizeof(sa)) != 0 || listen(srv, 64) != 0) {
        close(srv);
        return 2;
    }
    struct timeval atv = { 0, 150000 };
    setsockopt(srv, SOL_SOCKET, SO_RCVTIMEO, &atv, sizeof(atv));

    pthread_t rt;
    pthread_create(&rt, NULL, reaper_thread, NULL);

    double rss = 0.0, hwm = 0.0;
    read_proc_rss_mib(&rss, &hwm);
    printf("{\"ok\":true,\"event\":\"chimera_spine_ready\",\"engine\":\"chimera-micronucleus-c11\",\"pid\":%d,\"port\":%d,\"boot_rss_mib\":%.3f}\n",
           (int)getpid(), g_port, rss);
    fflush(stdout);

    while (!g_shutdown) {
        int cfd = accept(srv, NULL, NULL);
        if (cfd < 0) continue;
        int *pfd = (int *)malloc(sizeof(int));
        if (!pfd) { close(cfd); continue; }
        *pfd = cfd;
        pthread_t ct;
        pthread_attr_t attr;
        pthread_attr_init(&attr);
        pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
        if (pthread_create(&ct, &attr, client_thread, pfd) != 0) {
            close(cfd);
            free(pfd);
        }
        pthread_attr_destroy(&attr);
    }

    close(srv);
    pthread_join(rt, NULL);
    pthread_mutex_lock(&g_mu);
    organ_sleep_locked();
    for (int i = 0; i < MAX_GHOST_SLOTS; i++) free(g_ghost[i].data);
    pthread_mutex_unlock(&g_mu);
    return 0;
}
