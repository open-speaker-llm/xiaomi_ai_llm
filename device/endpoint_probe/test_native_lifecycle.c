/* Fake helper/control only. All files use a compile-time private test root. */
#include "native_wake_state.h"
#include "neural_stream.h"
#include "neural_decision.h"
#include "native_route.h"
#include <stdlib.h>
#include <assert.h>
static void put(const char *path,const void *data,size_t size){
    int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC,0600);assert(fd>=0);
    assert(write(fd,data,size)==(ssize_t)size);close(fd);
}
static void hold(pid_t owner){while(getppid()==owner && alive((uint32_t)owner))usleep(10000);}
int main(int argc,char **argv){
    setvbuf(stdout,NULL,_IOLBF,0);
    assert(argc>=2);
    if(!strcmp(argv[1],"assert-unarmed")){
        struct nw_state s;assert(nw_open(&s)<0);
        int fd=open(NW_FILE,O_RDONLY);assert(fd>=0 && read(fd,&s,sizeof(s))==sizeof(s));close(fd);
        assert(s.phase==NW_CANCELLED && !s.modified && !s.prepared);return 0;
    }
    if(!strcmp(argv[1],"init")){
        assert(argc==3);uint32_t pid=(uint32_t)strtoul(argv[2],NULL,10);assert(alive(pid));
        struct control c={.magic=CONTROL_MAGIC,.version=1,.mipns_pid=pid,.aivs_pid=pid};
        put(CONTROL_FILE,&c,sizeof(c));return 0;
    }
    if(!strcmp(argv[1],"idle-status")){
        struct nw_state s;int state=nw_open(&s);assert(state>=0);
        assert(s.phase==NW_ARMED && !s.modified && !s.prepared && !s.frames && alive(s.observer));
        char path[256],decision[272];nw_stream_path(path,sizeof(path),&s);
        struct neural_stream *stream=malloc(sizeof(*stream));assert(stream);
        int audio=open(path,O_RDONLY);assert(audio>=0);
        assert(read(audio,stream,sizeof(*stream))==sizeof(*stream));close(audio);
        assert(ns_identity(stream,s.nonce,s.owner) && stream->state==NS_WAIT &&
               stream->observer==s.observer && !stream->used && !stream->producer);
        snprintf(decision,sizeof(decision),"%s.decision",path);
        struct neural_decision d;int result=open(decision,O_RDONLY);assert(result>=0);
        assert(read(result,&d,sizeof(d))==sizeof(d));close(result);
        assert(nd_identity(&d,s.nonce,s.owner,s.observer) && !d.generation && !d.consumed && !d.invalid);
        printf("IDLE_STATUS owner=%u observer=%u nonce=%u remaining_ms=%d audio_bytes=%u proposals=%u clock_ticks=%ld\n",
            s.owner,s.observer,s.nonce,(int32_t)(s.deadline-now_ms()),stream->used,d.generation,sysconf(_SC_CLK_TCK));
        free(stream);nw_close(state,NULL);return 0;
    }
    if(!strcmp(argv[1],"cancel") || !strcmp(argv[1],"revoke")){
        struct nw_state s;int fd=nw_open(&s);assert(fd>=0 && s.phase==NW_BOUND);
        if(!strcmp(argv[1],"cancel"))nw_event(&s,s.expected_producer,1);
        else s.phase=NW_CANCELLED;
        nw_close(fd,&s);return 0;
    }
    if(!strcmp(argv[1],"complete") || !strcmp(argv[1],"begin")){
        int complete=!strcmp(argv[1],"complete");
        struct nw_state s;int fd=nw_open(&s);assert(fd>=0 && s.phase==NW_ARMED);
        s.phase=NW_BOUND;s.prepared=s.accepted=s.modified=1;
        s.ended=s.final_seen=s.finished=(uint32_t)complete;
        s.end_reason=(uint32_t)complete;s.producer=s.expected_producer;s.consumer=s.expected_consumer;
        snprintf(s.dialog,sizeof(s.dialog),"fixture-%u-%u",s.owner,s.nonce);assert(nr_begin(&s));
        char path[256];nw_stream_path(path,sizeof(path),&s);
        int audio=open(path,O_RDWR);assert(audio>=0);
        uint32_t done=complete?NS_DONE:NS_LIVE;assert(pwrite(audio,&done,4,24)==4);close(audio);
        nw_close(fd,&s);return 0;
    }
    assert(!strcmp(argv[1],"helper") && argc==6);
    const char *path=argv[2];uint32_t nonce=(uint32_t)strtoul(argv[3],NULL,10),owner=(uint32_t)strtoul(argv[4],NULL,10);
    const char *stage=getenv("LIFECYCLE_STAGE");assert(stage);
    printf("FIXTURE_HELPER stage=%s pid=%u\n",stage,(unsigned)getpid());
    if(!strcmp(stage,"before")){hold((pid_t)owner);return 1;}
    struct neural_stream *s=calloc(1,sizeof(*s));assert(s);ns_init(s,nonce,owner,(uint32_t)getpid());
    put(path,s,sizeof(*s));free(s);
    puts("FIXTURE_STREAM_WRITTEN");
    if(!strcmp(stage,"stream")){hold((pid_t)owner);return 1;}
    if(!strcmp(stage,"busy")){
        struct control c;int control=state_open(&c);assert(control>=0);
        c.owner=owner;c.phase=REQUEST;c.deadline=now_ms()+10000;state_close(control,&c);
    }
    struct neural_decision d;nd_init(&d,nonce,owner,(uint32_t)getpid());
    char decision[512];snprintf(decision,sizeof(decision),"%s.decision",path);put(decision,&d,sizeof(d));
    puts("FIXTURE_MAPPINGS_READY");
    int fd=open(path,O_RDONLY);assert(fd>=0);
    while(getppid()==(pid_t)owner && alive(owner)){
        uint32_t state;assert(pread(fd,&state,4,24)==4);
        if(state==NS_DONE){close(fd);return 0;}
        usleep(10000);
    }
    close(fd);return 1;
}
