#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <regex.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* Reads only newly appended AIVS instructions. Never pauses ASR or the recorder.
 * The client takes ownership by replacing our marker during fallback. If that
 * does not happen within 3 seconds, release our own pause (fail open). */
static volatile sig_atomic_t running = 1;
static void stop_guard(int sig) { (void)sig; running = 0; }
static const char *space(const char *p) { while (isspace((unsigned char)*p)) ++p; return p; }
static int hex4(const char *p) {
    int n = 0;
    for (int i = 0; i < 4; ++i) {
        unsigned char c = (unsigned char)p[i];
        if (!isxdigit(c)) return -1;
        n = n * 16 + (isdigit(c) ? c - '0' : tolower(c) - 'a' + 10);
    }
    return n;
}
static const char *string(const char *p, char *out, size_t cap) {
    size_t n = 0;
    if (*p++ != '"') return NULL;
    while (*p && *p != '"') {
        unsigned char c = (unsigned char)*p++;
        if (c < 32) return NULL;
        if (c == '\\') {
            c = (unsigned char)*p++;
            if (!c) return NULL;
            if (c == 'u') {
                if (strlen(p) < 4) return NULL;
                int u = hex4(p); p += 4;
                if (u < 0) return NULL;
                if (u >= 0xd800 && u <= 0xdbff) {
                    if (strncmp(p, "\\u", 2) || strlen(p + 2) < 4) return NULL;
                    int lo = hex4(p + 2); p += 6;
                    if (lo < 0xdc00 || lo > 0xdfff) return NULL;
                    u = 0x10000 + ((u - 0xd800) << 10) + lo - 0xdc00;
                } else if (u >= 0xdc00 && u <= 0xdfff) return NULL;
                if (!u || n + 4 >= cap) return NULL;
                if (u < 0x80) out[n++] = (char)u;
                else if (u < 0x800) { out[n++] = (char)(0xc0 | (u >> 6)); out[n++] = (char)(0x80 | (u & 63)); }
                else if (u < 0x10000) { out[n++] = (char)(0xe0 | (u >> 12)); out[n++] = (char)(0x80 | ((u >> 6) & 63)); out[n++] = (char)(0x80 | (u & 63)); }
                else { out[n++] = (char)(0xf0 | (u >> 18)); out[n++] = (char)(0x80 | ((u >> 12) & 63)); out[n++] = (char)(0x80 | ((u >> 6) & 63)); out[n++] = (char)(0x80 | (u & 63)); }
                continue;
            }
            switch (c) {
                case '"': case '\\': case '/': break;
                case 'b': c = '\b'; break; case 'f': c = '\f'; break;
                case 'n': c = '\n'; break; case 'r': c = '\r'; break; case 't': c = '\t'; break;
                default: return NULL;
            }
        }
        if (n + 1 >= cap) return NULL;
        out[n++] = (char)c;
    }
    if (*p != '"') return NULL;
    out[n] = 0; return p + 1;
}
static const char *skip(const char *p, int depth) {
    char scratch[65536];
    p = space(p);
    if (depth > 12) return NULL;
    if (*p == '"') return string(p, scratch, sizeof scratch);
    if (*p == '{' || *p == '[') {
        int object = *p == '{'; char end = object ? '}' : ']';
        p = space(p + 1);
        if (*p == end) return p + 1;
        for (;;) {
            if (object) { p = string(p, scratch, sizeof scratch); if (!p || *(p = space(p)) != ':') return NULL; ++p; }
            p = skip(p, depth + 1); if (!p) return NULL;
            p = space(p); if (*p == end) return p + 1;
            if (*p++ != ',') return NULL;
            p = space(p);
        }
    }
    if (!strncmp(p,"true",4)) return p+4;
    if (!strncmp(p,"false",5)) return p+5;
    if (!strncmp(p,"null",4)) return p+4;
    if (*p == '-' || isdigit((unsigned char)*p)) {
        char *end; (void)strtod(p, &end); return end == p ? NULL : end;
    }
    return NULL;
}
static const char *member(const char *p, const char *key) {
    char name[256];
    p = space(p); if (*p++ != '{') return NULL;
    for (;;) {
        p = space(p); if (*p == '}') return NULL;
        p = string(p,name,sizeof name); if (!p || *(p=space(p)) != ':') return NULL;
        p = space(p+1); if (!strcmp(name,key)) return p;
        p = skip(p,0); if (!p) return NULL;
        p = space(p); if (*p++ != ',') return NULL;
    }
}
static int value(const char *obj, const char *key, char *out, size_t cap) {
    const char *p = member(obj,key); return p && string(p,out,cap);
}
static int classify(const char *line, regex_t *pattern) {
    char name[128], ns[128], dialog[128], text[32768];
    const char *end = skip(line,0);
    if (!end || *space(end)) return 0;
    const char *header = member(line,"header"), *payload = member(line,"payload");
    if (!header || !payload || !value(header,"name",name,sizeof name) || strcmp(name,"Speak") ||
        !value(header,"namespace",ns,sizeof ns) || strcmp(ns,"SpeechSynthesizer") ||
        !value(header,"dialog_id",dialog,sizeof dialog) || !*dialog ||
        !value(payload,"text",text,sizeof text)) return 0;
    return regexec(pattern,text,0,NULL,0) == 0;
}
static double monotonic(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9;
}
static pid_t player_pid(void) {
    DIR *d=opendir("/proc"); if (!d) return 0;
    struct dirent *e; pid_t result=0;
    while ((e=readdir(d))) {
        if (!isdigit((unsigned char)e->d_name[0])) continue;
        char path[320], name[64]; snprintf(path,sizeof path,"/proc/%s/comm",e->d_name);
        FILE *f=fopen(path,"r"); if (!f) continue;
        if (fgets(name,sizeof name,f) && !strcmp(name,"mediaplayer\n")) result=(pid_t)atoi(e->d_name);
        fclose(f); if (result) break;
    }
    closedir(d); return result;
}
static int owned(const char *marker, const char *token) {
    char buf[128]; FILE *f=fopen(marker,"r"); if (!f) return 0;
    int yes=fgets(buf,sizeof buf,f) && !strcmp(buf,token); fclose(f); return yes;
}
static void release(const char *marker, const char *token, pid_t player) {
    if (!owned(marker,token)) return;
    if (player > 1) kill(player,SIGCONT);
    unlink(marker); fprintf(stderr,"GUARD_RELEASE reason=unclaimed_or_exit\n");
}
int main(int argc, char **argv) {
    if (argc != 3 && argc != 7) { fprintf(stderr,"usage: guard --classify regex | guard log marker busy owner_pid regex enable_marker\n"); return 2; }
    regex_t pattern;
    if (regcomp(&pattern,argc==3?argv[2]:argv[5],REG_EXTENDED|REG_NOSUB)) return 2;
    if (argc==3) {
        if (strcmp(argv[1],"--classify")) return 2;
        char *line=NULL; size_t cap=0;
        while (getline(&line,&cap,stdin)>0) puts(classify(line,&pattern)?"block":"pass");
        free(line); regfree(&pattern); return 0;
    }
    pid_t owner=(pid_t)atoi(argv[4]); if (owner<=1) return 2;
    signal(SIGTERM,stop_guard); signal(SIGINT,stop_guard);
    FILE *f=NULL; struct stat st, current; memset(&st,0,sizeof st);
    char token[128], line[65536]; size_t used=0; int drop=0, initial=1;
    snprintf(token,sizeof token,"guard:%ld\n",(long)getpid());
    double deadline=0; pid_t stopped=0;
    fprintf(stderr,"GUARD_READY poll_ms=10 lease_seconds=3\n");
    while (running && (kill(owner,0)==0 || errno==EPERM)) {
        if (deadline && (!owned(argv[2],token) || monotonic()>=deadline)) {
            release(argv[2],token,stopped); deadline=0; stopped=0;
        }
        if (stat(argv[1],&current)==0) {
            if (!f || current.st_ino!=st.st_ino || current.st_dev!=st.st_dev || current.st_size<ftell(f)) {
                if (f) fclose(f);
                f=fopen(argv[1],"r"); used=0; drop=0; st=current;
                if (f && initial) fseek(f,0,SEEK_END);
            }
            initial=0;
            if (f) {
                clearerr(f); int c;
                while ((c=fgetc(f))!=EOF) {
                    if (c=='\n') {
                        line[used]=0;
                        if (!drop && access(argv[6],F_OK)==0 && access(argv[3],F_OK)!=0 &&
                            access(argv[2],F_OK)!=0 && classify(line,&pattern)) {
                            pid_t pid=player_pid();
                            FILE *marker=pid>1?fopen(argv[2],"wx"):NULL;
                            if (marker) {
                                int ok=fputs(token,marker)>=0; ok=fclose(marker)==0 && ok;
                                if (ok && kill(pid,SIGSTOP)==0) {
                                    stopped=pid; deadline=monotonic()+3;
                                    fprintf(stderr,"GUARD_BLOCK monotonic=%.3f player=%ld\n",monotonic(),(long)pid);
                                } else unlink(argv[2]);
                            }
                        }
                        used=0; drop=0;
                    } else if (used+1<sizeof line) line[used++]=(char)c;
                    else drop=1;
                }
            }
        } else initial=0;
        struct timespec wait={0,10000000}; nanosleep(&wait,NULL);
    }
    release(argv[2],token,stopped);
    if (f) fclose(f);
    regfree(&pattern); return 0;
}
