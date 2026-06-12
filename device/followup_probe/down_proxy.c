// down_proxy <listen_path> <forward_path> <logfile> <flagfile>
// MITM for aivs -> mipns downward DGRAM control channel.
// Transparent forward by default. When <flagfile> exists, the next Dialog.Finish
// (inner type 0x05) is rewritten to keep the mic open: inject ExpectSpeech(0x02)
// for that dialog BEFORE forwarding Finish, then inject a fresh prepare(0x01)
// AFTER, so mipns reopens the mic for a no-wakeword followup turn.
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>

static struct sockaddr_un fwd;
static socklen_t fwdlen;
static int fd;
static FILE *lg;

static void sendfwd(const unsigned char *b, int n) {
    sendto(fd, b, n, 0, (struct sockaddr *)&fwd, fwdlen);
}

static int file_exists(const char *p) { struct stat s; return stat(p, &s) == 0; }

static void rand_id_hex(char out[32]) {
    static const char hx[] = "0123456789abcdef";
    int rf = open("/dev/urandom", O_RDONLY);
    unsigned char r[16];
    read(rf, r, 16); close(rf);
    for (int i = 0; i < 16; i++) { out[2*i] = hx[r[i] >> 4]; out[2*i+1] = hx[r[i] & 15]; }
}

int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "usage: %s listen forward log flag\n", argv[0]); return 2; }
    const char *listen_path = argv[1], *forward_path = argv[2], *logf = argv[3], *flag = argv[4];

    fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (fd < 0) { perror("socket"); return 1; }
    struct sockaddr_un la; memset(&la, 0, sizeof la); la.sun_family = AF_UNIX;
    strncpy(la.sun_path, listen_path, sizeof(la.sun_path) - 1);
    unlink(listen_path);
    if (bind(fd, (struct sockaddr *)&la, sizeof la) < 0) { perror("bind"); return 1; }
    chmod(listen_path, 0755);

    memset(&fwd, 0, sizeof fwd); fwd.sun_family = AF_UNIX;
    strncpy(fwd.sun_path, forward_path, sizeof(fwd.sun_path) - 1);
    fwdlen = sizeof fwd;

    lg = fopen(logf, "w"); setvbuf(lg, NULL, _IOLBF, 0);
    fprintf(lg, "[proxy] up listen=%s forward=%s\n", listen_path, forward_path);

    unsigned char buf[4096];
    int armed_done = 0;  // one-shot guard so we only rewrite one Finish per flag
    for (;;) {
        ssize_t n = recvfrom(fd, buf, sizeof buf, 0, NULL, NULL);
        if (n <= 0) continue;

        int type = (n >= 6 && buf[0]==0x08 && buf[2]==0x1a && buf[4]==0x08) ? buf[5] : -1;
        // log small control frames only
        if (n <= 64 && type >= 0) {
            char idp[9] = {0};
            if (n >= 16) memcpy(idp, buf + 8, 8);
            fprintf(lg, "[recv] type=0x%02x size=%zd id=%s\n", type, n, idp);
        }

        if (file_exists(flag) && type == 0x05 && n >= 40 && !armed_done) {
            // capture the dialog_id (32 ascii bytes at offset 8)
            unsigned char id[32]; memcpy(id, buf + 8, 32);
            // 1) inject continue/ExpectSpeech(0x03) for this dialog:
            //    08 01 1a 28 08 03 12 20 <id> 22 02 10 01
            unsigned char es[44] = {0x08,0x01,0x1a,0x28,0x08,0x03,0x12,0x20};
            memcpy(es + 8, id, 32);
            es[40]=0x22; es[41]=0x02; es[42]=0x10; es[43]=0x01;
            sendfwd(es, 44);
            fprintf(lg, "[inject] continue-directive(0x03) for finishing dialog\n");
            // 2) forward the original Finish
            sendfwd(buf, n);
            // 3) inject fresh prepare(0x01) to open mic: 08 01 1a 28 08 01 12 20 <newid> 1a 02 08 01
            char nid[32]; rand_id_hex(nid);
            unsigned char pr[44] = {0x08,0x01,0x1a,0x28,0x08,0x01,0x12,0x20};
            memcpy(pr + 8, nid, 32);
            pr[40]=0x1a; pr[41]=0x02; pr[42]=0x08; pr[43]=0x01;
            sendfwd(pr, 44);
            fprintf(lg, "[inject] fresh prepare(0x01) new dialog -> open mic\n");
            armed_done = 1;
            unlink(flag);
            continue;
        }
        if (!file_exists(flag)) armed_done = 0;  // re-arm when flag cleared+set again

        sendfwd(buf, n);
    }
    return 0;
}
