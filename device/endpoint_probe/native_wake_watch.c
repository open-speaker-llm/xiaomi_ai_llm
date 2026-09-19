/* Explicit bounded first-turn trial. Only a real wake opens the microphone. */
#include "native_wake_state.h"
#include "neural_stream.h"
#include "neural_decision.h"
#include "native_route.h"
#include "native_wake_recovery.h"
#include "native_parent.h"
#include <sys/wait.h>
#include <stdlib.h>
#include <errno.h>
#include <stddef.h>
#ifndef NW_HELPER_SCRIPT
#define NW_HELPER_SCRIPT "/tmp/xiaomi_neural_shadow/run_neural_shadow.sh"
#endif
#ifndef NW_READY_IDLE_MS
#define NW_READY_IDLE_MS 1200000u
#endif
static volatile sig_atomic_t running=1;
static pid_t session_parent;
static void stop_watch(int sig){(void)sig;running=0;}
static int watch_running(void){
    if(session_parent && getppid()!=session_parent)running=0;
    return running;
}
static int private_read(const char *path,void *out,size_t size,off_t total){
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return 0;
    struct stat st;int ok=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_uid==geteuid() &&
        !(st.st_mode&077) && st.st_size==total && !flock(fd,LOCK_SH) &&
        read(fd,out,size)==(ssize_t)size;
    close(fd);return ok;
}
int main(int argc,char **argv) {
    int warm=argc==2 && !strcmp(argv[1],"endpoint-ready");
    int tagged=argc==2 && (!strcmp(argv[1],"endpoint-tagged") || warm);
    int both=argc==2 && (!strcmp(argv[1],"endpoint-wakeup") || tagged);
    int endpoint=argc==2 && (!strcmp(argv[1],"endpoint") || both);
    if(argc!=1 && !endpoint)return 2;
    signal(SIGTERM,stop_watch);signal(SIGINT,stop_watch);setvbuf(stdout,NULL,_IOLBF,0);
    const char *parent=getenv("NATIVE_WAKE_PARENT_PID");
    if(parent){
        char *end;long value=strtol(parent,&end,10);
        if(!*parent || *end || value<=1 || value>INT32_MAX)return 2;
        session_parent=(pid_t)value;if(!native_bind_parent(session_parent))return 2;
    }
    int watcher_lock=nw_watch_lock();
    if(watcher_lock<0)return errno==EWOULDBLOCK || errno==EAGAIN?3:2;
    /* FD_CLOEXEC prevents the helper retaining this lock after exec. The OS
     * releases it on all watcher exits, including SIGKILL. */
    int recovered=nw_recover_abandoned();if(recovered)return recovered;
    if(endpoint){
        int pruned=nr_prune_completed(32);if(pruned<0)return 2;
        if(pruned)printf("FIRST_ROUTE_PRUNED quiet=%d protected=retained\n",pruned);
        if(!nr_has_capacity()){puts("FIRST_ROUTE_CAPACITY protected-full action=no-arm");return 2;}
    }
    struct nw_state s={.magic=NW_MAGIC,.owner=(uint32_t)getpid(),
        .deadline=now_ms()+(endpoint?90000:45000),.phase=NW_ARMED};
    char path[256]={0},decision_path[272]={0};pid_t helper=-1;int helper_rc=-1,created=0,rc=1;
    if(endpoint){
        struct control native;int control_fd=state_open(&native);
        int healthy=control_fd>=0 && alive(native.mipns_pid) && alive(native.aivs_pid);
        int busy=control_fd>=0 && active(&native);
        if(control_fd>=0)state_close(control_fd,NULL);
        if(!healthy)return 2;
        if(busy || access("/tmp/native_first_busy",F_OK)==0 || access("/tmp/mipns/mute",F_OK)==0)return 3;
        s.mode=tagged?3:(both?2:1);s.nonce=now_ms();if(!s.nonce)s.nonce=1;
        if(tagged){
            int random=open("/dev/urandom",O_RDONLY|O_CLOEXEC);if(random<0)return 2;
            ssize_t n=read(random,s.tag,sizeof(s.tag));close(random);
            if(n!=sizeof(s.tag) || !nw_tag_valid(s.tag))return 2;
        }
        s.expected_producer=native.mipns_pid;s.expected_consumer=native.aivs_pid;
        nw_stream_path(path,sizeof(path),&s);snprintf(decision_path,sizeof(decision_path),"%s.decision",path);
        if(access(path,F_OK)==0 || access(decision_path,F_OK)==0 || access(NW_FILE,F_OK)==0)return 2;
        /* CANCELLED is deliberately non-live: no real wake can acquire the
         * generation while loading. Publish ownership BEFORE starting helper. */
        s.phase=NW_CANCELLED;
        int stage=open(NW_FILE,O_RDWR|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
        if(stage<0)return 2;
        created=1;
        if(write(stage,&s,sizeof(s))!=sizeof(s)){close(stage);goto cleanup;}
        int gate[2];if(pipe(gate)){close(stage);goto cleanup;}
        helper=fork();
        if(helper<0){close(stage);close(gate[0]);close(gate[1]);goto cleanup;}
        if(!helper){
            close(stage);close(gate[1]);close(watcher_lock);
            signal(SIGTERM,SIG_DFL);
            if(!native_bind_parent((pid_t)s.owner))_exit(1);
            char go;ssize_t received=read(gate[0],&go,1);close(gate[0]);
            if(received!=1 || go!='G' || getppid()!=(pid_t)s.owner)_exit(1);
            char nonce[24],owner[24];snprintf(nonce,sizeof(nonce),"%u",s.nonce);snprintf(owner,sizeof(owner),"%u",s.owner);
            execl("/bin/sh","sh",NW_HELPER_SCRIPT,path,nonce,owner,warm?"first-ready":"first-endpoint",(char *)NULL);
            _exit(127);
        }
        close(gate[0]);
        s.observer=(uint32_t)helper;
        int staged=pwrite(stage,&s,sizeof(s),0)==sizeof(s);close(stage);
        /* Ignore SIGPIPE if child died before the handshake. */
        signal(SIGPIPE,SIG_IGN);
        int released=staged && write(gate[1],"G",1)==1;close(gate[1]);
        if(!released)goto cleanup;
        printf("FIRST_PRELOAD owner=%u observer=%u nonce=%u\n",s.owner,s.observer,s.nonce);
        int ready=0;
        for(unsigned attempt=0;watch_running() && attempt<500;attempt++){
            int status;
            if(waitpid(helper,&status,WNOHANG)==helper){helper_rc=status;helper=-1;break;}
            struct neural_stream header;struct neural_decision d;
            if(private_read(path,&header,offsetof(struct neural_stream,pcm),sizeof(header)) &&
               ns_identity(&header,s.nonce,s.owner) && header.observer==s.observer &&
               header.state==NS_WAIT && !header.producer && !header.used &&
               private_read(decision_path,&d,sizeof(d),sizeof(d)) && nd_identity(&d,s.nonce,s.owner,s.observer)){
                ready=1;break;
            }
            usleep(20000);
        }
        if(!ready || !watch_running())goto cleanup;
        /* Playback/followup may start while the model is loading. Recheck
         * immediately before arming; temporary busy is retryable, not broken. */
        control_fd=state_open(&native);
        healthy=control_fd>=0 && native.mipns_pid==s.expected_producer && native.aivs_pid==s.expected_consumer &&
            alive(native.mipns_pid) && alive(native.aivs_pid);
        busy=control_fd>=0 && active(&native);
        if(control_fd>=0)state_close(control_fd,NULL);
        if(!healthy){rc=2;goto cleanup;}
        if(busy || access("/tmp/native_first_busy",F_OK)==0 || access("/tmp/mipns/mute",F_OK)==0){rc=3;goto cleanup;}
    }
    int fd=open(NW_FILE,O_WRONLY|O_CLOEXEC|O_NOFOLLOW|(created?0:O_CREAT|O_EXCL),0600);
    if(fd<0)goto cleanup;
    created=1;
    s.phase=NW_ARMED;
    if(write(fd,&s,sizeof(s))!=sizeof(s)){close(fd);goto cleanup;}close(fd);
    printf("%s owner=%u nonce=%u arm_window_s=%u action=%s\n",endpoint?"FIRST_ENDPOINT_READY":"WAKE_OBSERVER_READY",s.owner,s.nonce,warm?NW_READY_IDLE_MS/1000:45,endpoint?"native-first-endpoint":"observe-only");
    uint32_t last=NW_ARMED,arm_started=now_ms();
    struct nw_state current=s;
    while(watch_running() && (int32_t)(s.deadline-now_ms())>0){
        usleep(20000);
        if(helper>1){int status;if(waitpid(helper,&status,WNOHANG)==helper){helper_rc=status;helper=-1;}}
        if(!private_read(NW_FILE,&current,sizeof(current),sizeof(current)) ||
           current.magic!=s.magic || current.owner!=s.owner || current.nonce!=s.nonce ||
           current.deadline!=s.deadline || !memchr(current.dialog,0,sizeof(current.dialog)))break;
        if(current.phase!=last){
            last=current.phase;
            printf("WAKE_OBSERVER phase=%u producer=%u consumer=%u dialog=%s\n",last,current.producer,current.consumer,current.dialog);
        }
        if(last==NW_CANCELLED){
            if(endpoint && current.end_reason==NW_END_REPLACED)rc=5;
            break;
        }
        if(endpoint){
            if(last==NW_ARMED){
                if(helper<0)break;
                if((uint32_t)(now_ms()-arm_started)>(warm?NW_READY_IDLE_MS:45000u)){rc=4;break;}
                if(warm && (int32_t)(s.deadline-now_ms())<60000){
                    struct nw_state renewed;int renewal=nw_open(&renewed);
                    int extended=renewal>=0 && renewed.owner==s.owner && renewed.nonce==s.nonce &&
                        !memcmp(renewed.tag,s.tag,NW_TAG_BYTES) && nw_renew_idle(&renewed,s.owner,now_ms());
                    if(renewal>=0)nw_close(renewal,extended?&renewed:NULL);
                    if(extended){s.deadline=renewed.deadline;printf("FIRST_IDLE_RENEW owner=%u nonce=%u\n",s.owner,s.nonce);}
                }
            }
            if(current.final_seen && current.finished){rc=current.modified && !current.failed && current.end_reason==1?0:1;break;}
            if(current.wake_ms && (uint32_t)(now_ms()-current.wake_ms)>30000)break;
        }
    }
    if(!endpoint)rc=last==NW_BOUND?0:1;
    printf("FIRST_TRIAL_DONE endpoint=%d modified=%u ended=%u final=%u finished=%u failed=%u frames=%u dialog=%s rc=%d\n",
        endpoint,current.modified,current.ended,current.final_seen,current.finished,current.failed,current.frames,current.dialog,rc);
cleanup:
    if(endpoint && !rc && helper>1){
        for(unsigned n=0;n<100;n++){
            if(waitpid(helper,&helper_rc,WNOHANG)==helper){helper=-1;break;}usleep(10000);
        }
    }
    if(helper>1){
        kill(helper,SIGTERM);
        for(unsigned n=0;n<100;n++){
            if(waitpid(helper,&helper_rc,WNOHANG)==helper){helper=-1;break;}usleep(10000);
        }
        if(helper>1){kill(helper,SIGKILL);(void)waitpid(helper,&helper_rc,0);}
    }
    if(endpoint){
        if(rc==0 && (helper_rc<0 || !WIFEXITED(helper_rc) || WEXITSTATUS(helper_rc)))rc=1;
        printf("FIRST_HELPER_WAIT status=%d trial_rc=%d\n",helper_rc,rc);
    }
    if(created){
        /* Publish permission only after helper completion and a fresh locked
         * final-state check. Owner death before this leaves pending in place. */
        struct nw_state final_state;int route_fd=nw_open(&final_state);
        if(route_fd>=0){
            if(final_state.owner==s.owner && final_state.nonce==s.nonce &&
               final_state.deadline==s.deadline && !memcmp(final_state.tag,s.tag,NW_TAG_BYTES) &&
               final_state.modified){
                int complete=nr_complete(&final_state,rc==0);
                if(!nr_finish(&final_state,complete) || !complete)rc=1;
                printf("FIRST_ROUTE_DONE dialog=%s allowed=%d rc=%d\n",final_state.dialog,complete && !rc,rc);
            }else if(endpoint && rc==0)rc=1;
            nw_close(route_fd,NULL);
        }else if(endpoint && rc==0)rc=1;
        struct nw_state own;
        if(private_read(NW_FILE,&own,sizeof(own),sizeof(own)) && own.owner==s.owner && own.nonce==s.nonce)unlink(NW_FILE);
    }
    if(endpoint){unlink(path);unlink(decision_path);}
    return rc;
}
