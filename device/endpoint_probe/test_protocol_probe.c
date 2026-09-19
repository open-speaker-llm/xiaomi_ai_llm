/* Independent device process: no native services/microphone/cloud calls. */
#define CONTROL_DIR "/tmp/xiaomi_endpoint_protocol_unit"
#undef PROBE_DIR
#define PROBE_DIR CONTROL_DIR
#define NATIVE_BUSY_FILE CONTROL_DIR "/busy"
#include "protocol_probe.c"
#undef NDEBUG
#include <assert.h>
static void fake_end(unsigned code) {(void)code;assert(!"must not call a live end callback");}
static unsigned calls;
#ifdef PROBE_ACTIVE_ENDPOINT
static void *expected_pcm;
static unsigned delivered;
static unsigned char expected_contents[1920];
static void fake_asr(void *ctx,void *data,unsigned bytes) {
    assert(ctx==NULL && data==expected_pcm && bytes==1920);
    assert(!memcmp(data,expected_contents,bytes));delivered++;
}
static void capture_trial(struct control *s,uint32_t seq,uint32_t capture_seq) {
    s->sequence=seq;
    char text[80];int n=snprintf(text,sizeof(text),"%u %u 5\n",seq,s->owner);
    int fd=open(PROBE_DIR "/armed",O_WRONLY|O_TRUNC);assert(fd>=0);
    assert(write(fd,text,(size_t)n)==n);close(fd);
    fd=open(CONTROL_FILE,O_WRONLY|O_TRUNC);assert(fd>=0);
    assert(write(fd,s,sizeof(*s))==sizeof(*s));close(fd);
    if(capture_seq) {
        n=snprintf(text,sizeof(text),"%u %u 5\n",capture_seq,s->owner);
        fd=open(PROBE_DIR "/capture.armed",O_CREAT|O_WRONLY|O_TRUNC,0600);assert(fd>=0);
        assert(write(fd,text,(size_t)n)==n);close(fd);
    }
    assert(load_replay(s));
}
#endif
static void fake_wake(void *ctx,unsigned code,float angle) {
    (void)ctx;(void)angle;assert(code==1);assert(!replay_loaded && end_sent);calls++;
}
int main(void) {
    assert(mkdir(PROBE_DIR,0700)==0);
    struct control s={.magic=CONTROL_MAGIC,.version=1,.sequence=23,
        .owner=(uint32_t)getpid(),.deadline=now_ms()+20000,.phase=BOUND};
    for(unsigned p=IDLE;p<=NATIVE_HANDOFF;p++) {
        s.phase=p;assert(eligible(&s,23,s.owner)==(p>=TRIGGERED && p<=BOUND));
    }
    s.phase=BOUND;assert(!eligible(&s,22,s.owner));assert(!eligible(&s,23,s.owner+1));
    s.mipns_pid=s.aivs_pid=(uint32_t)getpid();assert(end_lease_owned(&s,23,s.owner));
    s.mipns_pid=1;assert(!end_lease_owned(&s,23,s.owner));s.mipns_pid=(uint32_t)getpid();
    s.aivs_pid=1;assert(!end_lease_owned(&s,23,s.owner));s.aivs_pid=(uint32_t)getpid();
    assert(scoped_timeout(&s,23,s.owner,3,0)==20000);
    assert(scoped_timeout(&s,23,s.owner,2,0)==0);
    assert(scoped_timeout(&s,22,s.owner,3,6000)==6000);
    s.phase=NATIVE_HANDOFF;assert(scoped_timeout(&s,23,s.owner,3,6000)==6000);
    s.phase=BOUND;s.final_seen=1;assert(scoped_timeout(&s,23,s.owner,3,6000)==6000);
    s.final_seen=0;s.deadline=now_ms()-1;assert(scoped_timeout(&s,23,s.owner,3,6000)==6000);
    s.deadline=now_ms()+20000;
    s.final_seen=1;assert(!eligible(&s,23,s.owner));s.final_seen=0;
    s.deadline=now_ms()-1;assert(!eligible(&s,23,s.owner));s.deadline=now_ms()+20000;
    unsigned seq,owner,vad;assert(!config(&seq,&owner,&vad));
    int fd=open(PROBE_DIR "/armed",O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0);
    char text[80];int n=snprintf(text,sizeof(text),"23 %u 0\n",s.owner);
    assert(write(fd,text,(size_t)n)==n);close(fd);
    assert(config(&seq,&owner,&vad) && seq==23 && owner==s.owner && !vad);
    assert(chmod(PROBE_DIR "/armed",0644)==0);assert(!config(&seq,&owner,&vad));
    assert(chmod(PROBE_DIR "/armed",0600)==0);
    unsigned char pcm[32000];memset(pcm,9,sizeof(pcm));
    fd=open(PROBE_DIR "/input.pcm",O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0);
    assert(write(fd,pcm,sizeof(pcm))==sizeof(pcm));close(fd);
    oneshot=fake_end;assert(load_replay(&s));assert(replay_bytes==32000 && !replay_used);
    assert(!memcmp(replay,pcm,sizeof(pcm)));
    chained_wake=fake_wake;probe_wake(NULL,1,0);assert(calls==1);
    assert(!load_replay(&s)); /* A physical wake cannot rearm the same replay. */
#ifdef PROBE_ACTIVE_ENDPOINT
    assert(scoped_timeout(&s,23,s.owner,4,0)==25000);
    strcpy(s.dialog,"test-dialog");
    assert(sdk_timeout_scope(&s,23,s.owner,3,10));
    assert(!sdk_timeout_scope(&s,22,s.owner,3,10));
    assert(!sdk_timeout_scope(&s,23,s.owner+1,3,10));
    assert(!sdk_timeout_scope(&s,23,s.owner,2,10));
    assert(sdk_timeout_scope(&s,23,s.owner,6,10));
    assert(sdk_timeout_scope(&s,23,s.owner,7,10));
    assert(!sdk_timeout_scope(&s,23,s.owner,8,10));
    assert(!sdk_timeout_scope(&s,23,s.owner,3,0));
    assert(!sdk_timeout_scope(&s,23,s.owner,3,-1));
    assert(!sdk_timeout_scope(&s,23,s.owner,3,30));
    assert(!sdk_timeout_scope(&s,23,s.owner,3,60));
    s.dialog[0]=0;assert(!sdk_timeout_scope(&s,23,s.owner,3,10));
    strcpy(s.dialog,"test-dialog");
    s.aivs_pid=1;assert(!sdk_timeout_scope(&s,23,s.owner,3,10));
    s.aivs_pid=(uint32_t)getpid();
    s.mipns_pid=1;assert(!sdk_timeout_scope(&s,23,s.owner,3,10));
    s.mipns_pid=(uint32_t)getpid();
    s.deadline=now_ms()-1;assert(!sdk_timeout_scope(&s,23,s.owner,3,10));
    s.deadline=now_ms()+20000;
    for(unsigned p=IDLE;p<=NATIVE_HANDOFF;p++) {
        s.phase=p;assert(sdk_timeout_scope(&s,23,s.owner,3,10)==(p==BOUND || p==RESULT));
    }
    s.phase=RESULT;s.final_seen=1;assert(sdk_timeout_scope(&s,23,s.owner,3,10));
    s.finished=1;
    for(unsigned p=IDLE;p<=NATIVE_HANDOFF;p++) {
        s.phase=p;
        assert(sdk_timeout_scope(&s,23,s.owner,3,10)==
               (p==BOUND || p==RESULT || p==COMPLETE || p==IDLE));
    }
    s.phase=IDLE;s.finished=0;assert(!sdk_timeout_scope(&s,23,s.owner,3,10));
    s.finished=1;s.final_seen=0;assert(!sdk_timeout_scope(&s,23,s.owner,3,10));
    s.final_seen=1;s.deadline=now_ms()-1;assert(!sdk_timeout_scope(&s,23,s.owner,3,10));
    s.deadline=now_ms()+20000;
    assert(!sdk_timeout_scope(&s,24,s.owner,3,10));
    s.finished=0;
    s.phase=BOUND;s.final_seen=0;
    assert(scoped_timeout(&s,23,s.owner,5,0)==25000);
    assert(scoped_timeout(&s,23,s.owner,6,0)==30000);
    assert(scoped_timeout(&s,23,s.owner,7,0)==30000);
    assert(scoped_timeout(&s,23,s.owner,8,0)==0);
    active_vad=fvad_new();assert(active_vad);
    s.sequence=24;role=1;
    fd=open(PROBE_DIR "/armed",O_WRONLY|O_TRUNC);assert(fd>=0);
    n=snprintf(text,sizeof(text),"24 %u 5\n",s.owner);
    assert(write(fd,text,(size_t)n)==n);close(fd);
    fd=open(CONTROL_FILE,O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0);
    assert(write(fd,&s,sizeof(s))==sizeof(s));close(fd);
    assert(load_replay(&s) && active_mode==5 && !replay_bytes);
    unsigned char block[1920]={0};expected_pcm=block;chained_asr=fake_asr;
    replay_asr(NULL,block,sizeof(block));assert(delivered==1 && active_endpoint.frames==6);
    probe_wake(NULL,1,0);assert(calls==2 && !replay_loaded);
    replay_asr(NULL,block,sizeof(block));assert(delivered==2 && active_endpoint.frames==6);
    /* The same cancelled generation forwards PCM, but never resumes its VAD. */
    s.sequence=25;
    fd=open(PROBE_DIR "/armed",O_WRONLY|O_TRUNC);assert(fd>=0);
    n=snprintf(text,sizeof(text),"25 %u 5\n",s.owner);
    assert(write(fd,text,(size_t)n)==n);close(fd);
    fd=open(CONTROL_FILE,O_WRONLY|O_TRUNC);assert(fd>=0);
    assert(write(fd,&s,sizeof(s))==sizeof(s));close(fd);
    assert(load_replay(&s) && !active_endpoint.frames && !active_endpoint.reason && !end_sent);
    assert(replay_seq==25 && !replay_used && !replay_bytes);
    for(unsigned i=0;i<sizeof(block);i++)block[i]=(unsigned char)(i*7+3);
    memcpy(expected_contents,block,sizeof(block));
    replay_asr(NULL,block,sizeof(block));assert(delivered==3 && active_endpoint.frames==6);
    assert(!memcmp(block,expected_contents,sizeof(block)));
    /* A new lease resets the detector; it cannot substitute last round's PCM. */
    assert(!diagnostic_capture.enabled && !diagnostic_capture.used);
    capture_trial(&s,26,25); /* stale capture consent cannot follow a new lease */
    replay_asr(NULL,block,sizeof(block));assert(!diagnostic_capture.used);
    capture_trial(&s,27,27);
    assert(diagnostic_capture.enabled);
    replay_asr(NULL,block,sizeof(block));assert(diagnostic_capture.used==sizeof(block));
    assert(!memcmp(diagnostic_capture.pcm,block,sizeof(block)));
    probe_wake(NULL,1,0);assert(!diagnostic_capture.enabled && !diagnostic_capture.used);
    capture_trial(&s,28,28);
    replay_asr(NULL,block,sizeof(block));
    capture_save(s.sequence,s.owner);
    char captured[192];snprintf(captured,sizeof(captured),PROBE_DIR "/capture.%u.%u.pcm",s.sequence,s.owner);
    fd=open(captured,O_RDONLY);assert(fd>=0);struct stat capture_stat;
    assert(!fstat(fd,&capture_stat) && capture_stat.st_size==1920 && !(capture_stat.st_mode&077));
    unsigned char saved[1920];assert(read(fd,saved,sizeof(saved))==sizeof(saved));close(fd);
    assert(!memcmp(saved,block,sizeof(saved)));
    capture_reset(&diagnostic_capture,1);capture_append(&diagnostic_capture,block,sizeof(block));
    capture_save(s.sequence,s.owner); /* O_EXCL refuses to overwrite the first capture */
    fd=open(captured,O_RDONLY);assert(fd>=0);
    assert(read(fd,saved,sizeof(saved))==sizeof(saved));close(fd);
    assert(!memcmp(saved,block,sizeof(saved)) && !diagnostic_capture.enabled);
    assert(unlink(captured)==0);assert(unlink(PROBE_DIR "/capture.armed")==0);
    capture_trial(&s,29,0);assert(!diagnostic_capture.enabled && !diagnostic_capture.used);
    /* A dedicated, exact-lease observer receives original PCM. It can never
     * cause quiet EOF, and a real wake revokes its mapped stream immediately. */
    s.sequence=30;
    char stream_path[192];snprintf(stream_path,sizeof(stream_path),PROBE_DIR "/shadow.%u.%u.stream",s.sequence,s.owner);
    fd=open(stream_path,O_CREAT|O_EXCL|O_RDWR,0600);assert(fd>=0);
    assert(!ftruncate(fd,sizeof(struct neural_stream)));
    struct neural_stream *observe=mmap(NULL,sizeof(*observe),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    close(fd);assert(observe!=MAP_FAILED);ns_init(observe,30,s.owner,(uint32_t)getpid());
    assert(!neural_open(31,s.owner,6));assert(!neural_stream);
    n=snprintf(text,sizeof(text),"30 %u 6\n",s.owner);
    fd=open(PROBE_DIR "/armed",O_WRONLY|O_TRUNC);assert(fd>=0);assert(write(fd,text,n)==n);close(fd);
    fd=open(CONTROL_FILE,O_WRONLY|O_TRUNC);assert(fd>=0);assert(write(fd,&s,sizeof(s))==sizeof(s));close(fd);
    assert(load_replay(&s) && active_mode==6 && neural_stream);
    unsigned prior=delivered;replay_asr(NULL,block,sizeof(block));
    assert(delivered==prior+1 && observe->used==sizeof(block) && observe->state==NS_LIVE);
    assert(!memcmp(observe->pcm,block,sizeof(block)) && !active_endpoint.reason);
    probe_wake(NULL,1,0);assert(!neural_stream && observe->state==NS_INVALID);
    replay_asr(NULL,block,sizeof(block));assert(observe->used==sizeof(block));
    munmap(observe,sizeof(*observe));assert(!unlink(stream_path));
    /* Mode 7 opens its proposal read-only and requires the same observer. */
    snprintf(stream_path,sizeof(stream_path),PROBE_DIR "/shadow.31.%u.stream",s.owner);
    fd=open(stream_path,O_CREAT|O_EXCL|O_RDWR,0600);assert(fd>=0);
    assert(!ftruncate(fd,sizeof(struct neural_stream)));
    observe=mmap(NULL,sizeof(*observe),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);close(fd);
    assert(observe!=MAP_FAILED);ns_init(observe,31,s.owner,(uint32_t)getpid());
    char decision_path[220];snprintf(decision_path,sizeof(decision_path),"%s.decision",stream_path);
    fd=open(decision_path,O_CREAT|O_EXCL|O_RDWR,0600);assert(fd>=0);
    assert(!ftruncate(fd,sizeof(struct neural_decision)));
    struct neural_decision *proposal=mmap(NULL,sizeof(*proposal),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);close(fd);
    assert(proposal!=MAP_FAILED);nd_init(proposal,31,s.owner,(uint32_t)getpid());
    assert(neural_open(31,s.owner,7) && neural_decision);
    assert(ns_append(neural_stream,block,sizeof(block)));
    nd_publish(proposal,(struct neural_proposal){(uint32_t)getpid(),6,6,now_ms(),0});
    assert(nd_due(neural_stream,neural_decision,31,s.owner,(uint32_t)getpid(),now_ms()));
    proposal->owner++;assert(!nd_due(neural_stream,neural_decision,31,s.owner,(uint32_t)getpid(),now_ms()));
    proposal->owner--;neural_close(0);assert(observe->state==NS_INVALID);
    assert(!neural_stream && !neural_decision);
    munmap(observe,sizeof(*observe));munmap(proposal,sizeof(*proposal));
    assert(!unlink(stream_path) && !unlink(decision_path));
    assert(unlink(CONTROL_FILE)==0);fvad_free(active_vad);active_vad=NULL;role=0;
#endif
    assert(unlink(PROBE_DIR "/armed")==0);
    assert(!load_replay(&s));
    unlink(PROBE_DIR "/input.pcm");unlink(PROBE_DIR "/events.log");assert(rmdir(PROBE_DIR)==0);
    puts("PASS: phase/owner/sequence/deadline/final gates, private config, PCM load, physical wake revocation");
    return 0;
}
