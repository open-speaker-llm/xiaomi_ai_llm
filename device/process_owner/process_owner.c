/* Linux session owner for native-first workers. No global process-name kills. */
#define _GNU_SOURCE
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <signal.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/wait.h>
#include <dirent.h>

static int paths(const char *pidfile, char *owner, char *lock, size_t n) {
    return snprintf(owner,n,"%s.owner",pidfile) < (int)n && snprintf(lock,n,"%s.lock",pidfile) < (int)n;
}
static int proc_info(pid_t pid, char *state, long *group, long *session, unsigned long long *start) {
    char path[64], buf[4096], *p, *tok, *save = NULL; int field=3;
    snprintf(path,sizeof(path),"/proc/%ld/stat",(long)pid);
    FILE *f=fopen(path,"r"); if(!f) return -1;
    if(!fgets(buf,sizeof(buf),f)) { fclose(f); return -1; } fclose(f);
    p=strrchr(buf,')'); if(!p || p[1]!=' ') return -1; p+=2;
    for(tok=strtok_r(p," ",&save);tok;tok=strtok_r(NULL," ",&save),field++) {
        if(field==3) *state=*tok; else if(field==5) *group=strtol(tok,NULL,10);
        else if(field==6) *session=strtol(tok,NULL,10);
        else if(field==22) { *start=strtoull(tok,NULL,10); return 0; }
    }
    return -1;
}
static int cmd_matches(pid_t pid, const char *script) {
    char path[64], buf[8192]; ssize_t n; int fd; size_t i=0;
    snprintf(path,sizeof(path),"/proc/%ld/cmdline",(long)pid);
    fd=open(path,O_RDONLY|O_CLOEXEC); if(fd<0) return 0;
    n=read(fd,buf,sizeof(buf)-1);close(fd);if(n<=0)return 0;buf[n]=0;
    while(i<(size_t)n) { size_t len=strnlen(buf+i,(size_t)n-i); if(strcmp(buf+i,script)==0)return 1; i+=len+1; }
    return 0;
}
static long proc_parent(pid_t pid) {
    char path[64], buf[4096], *end; long parent=-1; char state;
    snprintf(path,sizeof(path),"/proc/%ld/stat",(long)pid);
    FILE *f=fopen(path,"r"); if(!f)return -1;
    if(!fgets(buf,sizeof(buf),f)){fclose(f);return -1;}fclose(f);
    end=strrchr(buf,')');
    if(!end || sscanf(end+1," %c %ld",&state,&parent)!=2)return -1;
    return parent;
}
static int stop_owned(const char *pidfile,const char *owner,const char *script) {
    long pid, group=0, session=0; unsigned long long wanted,start=0; char state=0,extra; FILE *f=fopen(owner,"r");
    if(!f) {
        if(errno!=ENOENT) return -1;
        f=fopen(pidfile,"r"); if(!f) return errno==ENOENT?0:-1;
        if(fscanf(f,"%ld",&pid)!=1 || pid<=1) { fclose(f); return -1; } fclose(f);
        if(kill((pid_t)pid,0)==0 || errno==EPERM) { fprintf(stderr,"unmanaged PID file; refusing to signal\n"); return -1; }
        if(errno!=ESRCH)return -1;
        return unlink(pidfile)==0 || errno==ENOENT ? 0 : -1;
    }
    if(fscanf(f,"%ld %llu %c",&pid,&wanted,&extra)!=2 || pid<=1) { fclose(f); return -1; } fclose(f);
    long declared=0;
    f=fopen(pidfile,"r");
    if(!f || fscanf(f,"%ld %c",&declared,&extra)!=1 || declared!=pid) {
        if(f)fclose(f);
        fprintf(stderr,"PID file does not match owner; refusing to signal\n");return -1;
    }
    fclose(f);
    if(proc_info((pid_t)pid,&state,&group,&session,&start)!=0) {
        if(kill((pid_t)-pid,0)==0 || errno==EPERM) { fprintf(stderr,"orphaned session: refusing unverified signal\n"); return -1; }
        if(errno!=ESRCH)return -1;
        unlink(owner);unlink(pidfile);return 0;
    }
    if(start!=wanted || group!=pid || session!=pid || !cmd_matches((pid_t)pid,script)) {
        fprintf(stderr,"owner identity mismatch; refusing to signal\n");return -1;
    }
    if(kill((pid_t)-pid,SIGTERM)!=0 && errno!=ESRCH)return -1;
    for(int i=0;i<100;i++) {
        struct timespec ts={0,100000000}; nanosleep(&ts,NULL);
        if(kill((pid_t)-pid,0)!=0 && errno==ESRCH) { unlink(owner);unlink(pidfile);return 0; }
    }
    /* Signal only while the original session leader still has its identity. */
    if(proc_info((pid_t)pid,&state,&group,&session,&start)!=0 || start!=wanted || group!=pid || session!=pid) {
        fprintf(stderr,"session leader exited before group; refusing escalation\n");return -1;
    }
    if(kill((pid_t)-pid,SIGKILL)!=0 && errno!=ESRCH)return -1;
    for(int i=0;i<50;i++) { struct timespec ts={0,100000000};nanosleep(&ts,NULL);if(kill((pid_t)-pid,0)!=0 && errno==ESRCH){unlink(owner);unlink(pidfile);return 0;} }
    fprintf(stderr,"owned session did not exit\n");return -1;
}
static volatile sig_atomic_t interrupted;
static void on_signal(int sig) { (void)sig; interrupted=1; }
static int group_members(pid_t leader) {
    DIR *dir=opendir("/proc"); struct dirent *entry; int count=0;
    if(!dir)return -1;
    while((entry=readdir(dir))) {
        char *end; long v=strtol(entry->d_name,&end,10), group=0,session=0;
        unsigned long long start=0;char state=0;
        if(*entry->d_name==0 || *end!=0 || v<=1 || v==leader)continue;
        if(proc_info((pid_t)v,&state,&group,&session,&start)==0 && group==leader && session==leader && state!='Z')count++;
    }
    closedir(dir);return count;
}
int main(int argc,char **argv) {
    char owner[1024],lock[1024],tmp[1100],state=0; long group=0,session=0; unsigned long long start=0;
    if(argc>=3 && strcmp(argv[1],"detach")==0) { if(setsid()<0){perror("setsid detach");return 1;} execv(argv[2],argv+2);perror("exec detach");return 1; }
    if(argc<4 || !paths(argv[2],owner,lock,sizeof(owner)))return 2;
    if(strcmp(argv[1],"check")==0 && argc==4) {
        FILE *f=fopen(owner,"r");long pid;unsigned long long wanted;
        if(!f || fscanf(f,"%ld %llu",&pid,&wanted)!=2) { if(f)fclose(f);return 1; }fclose(f);
        char self_state=0;long self_group=0,self_session=0;unsigned long long self_start=0;
        if(pid<=1 || proc_parent(getppid())!=pid || !cmd_matches(getppid(),argv[3]) ||
           proc_info((pid_t)pid,&state,&group,&session,&start)!=0 ||
           start!=wanted || group!=pid || session!=pid || !cmd_matches((pid_t)pid,argv[3]) ||
           proc_info(getpid(),&self_state,&self_group,&self_session,&self_start)!=0 ||
           self_group!=pid || self_session!=pid)return 1;
        return 0;
    }
    int fd=open(lock,O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0 || flock(fd,LOCK_EX)!=0){perror("lock");return 1;}
    if(strcmp(argv[1],"stop")==0 && argc==4) return stop_owned(argv[2],owner,argv[3])==0?0:1;
    if(strcmp(argv[1],"run")!=0 || argc!=5)return 2;
    if(stop_owned(argv[2],owner,argv[4])!=0)return 1;
    if(setsid()<0){perror("setsid");return 1;}
    pid_t pid=getpid();if(proc_info(pid,&state,&group,&session,&start)!=0 || group!=pid || session!=pid)return 1;
    snprintf(tmp,sizeof(tmp),"%s.new.%ld",owner,(long)pid);
    int o=open(tmp,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(o<0)return 1;
    char data[128];int len=snprintf(data,sizeof(data),"%ld %llu\n",(long)pid,start);
    if(write(o,data,(size_t)len)!=len || close(o)!=0 || rename(tmp,owner)!=0){unlink(tmp);return 1;}
    o=open(argv[2],O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC|O_NOFOLLOW,0600);if(o<0){unlink(owner);return 1;}
    len=snprintf(data,sizeof(data),"%ld\n",(long)pid);
    if(write(o,data,(size_t)len)!=len || close(o)!=0){unlink(owner);unlink(argv[2]);return 1;}
    struct sigaction action;memset(&action,0,sizeof(action));action.sa_handler=on_signal;sigemptyset(&action.sa_mask);
    if(sigaction(SIGTERM,&action,NULL)!=0 || sigaction(SIGINT,&action,NULL)!=0)return 1;
    pid_t child=fork();if(child<0){unlink(owner);unlink(argv[2]);return 1;}
    if(child==0) {
        signal(SIGTERM,SIG_DFL);signal(SIGINT,SIG_DFL);close(fd);
        if(setenv("NATIVE_PROCESS_SUPERVISED","1",1)!=0)_exit(1);
        execl(argv[3],argv[3],argv[4],(char *)NULL);perror("exec client");_exit(127);
    }
    close(fd);
    int done=0, status=0;
    for(;;) {
        if(!done) { pid_t w=waitpid(child,&status,WNOHANG);if(w==child){done=1;if(!interrupted)kill(-pid,SIGTERM);} }
        if(done) {
            int members=group_members(pid);
            if(members==0)break;
            if(members<0){fprintf(stderr,"cannot inspect owned session\n");return 1;}
        }
        struct timespec delay={0,250000000};nanosleep(&delay,NULL);
    }
    unlink(owner);unlink(argv[2]);
    return WIFEXITED(status)?WEXITSTATUS(status):1;
}
