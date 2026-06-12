// usock_send <socket_path> <hex_payload>
// Sends one datagram (hex-decoded) to a unix DGRAM socket.
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s <path> <hex>\n", argv[0]); return 2; }
    int fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (fd < 0) { perror("socket"); return 1; }
    struct sockaddr_un a;
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    strncpy(a.sun_path, argv[1], sizeof(a.sun_path) - 1);
    const char *h = argv[2];
    int n = strlen(h) / 2;
    unsigned char buf[2048];
    if (n > (int)sizeof(buf)) n = sizeof(buf);
    for (int i = 0; i < n; i++) sscanf(h + 2 * i, "%2hhx", &buf[i]);
    ssize_t r = sendto(fd, buf, n, 0, (struct sockaddr *)&a, sizeof a);
    if (r < 0) { perror("sendto"); return 1; }
    printf("sent %zd bytes to %s\n", r, argv[1]);
    return 0;
}
