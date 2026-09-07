/* Runs in a separate process on the matching speaker, without touching its
 * microphone, native daemons, production control file or cloud connection. */
#define CONTROL_DIR "/tmp/native_followup_unit"
#include "native_asr.c"
#undef NDEBUG
#include <assert.h>

static void header(json_value *v,const char *ns,const char *name,const char *id,int event) {
    j_ctor(v,7); void *h=j_member(v,"header");
    put_string(h,"namespace",ns); put_string(h,"name",name);
    put_string(h,event?"id":"dialog_id",id);
}
static void set_state_for_test(unsigned phase,const char *dialog) {
    struct control s={.magic=CONTROL_MAGIC,.version=1,.sequence=5,.owner=(uint32_t)getpid(),
        .deadline=now_ms()+20000,.phase=phase};
    snprintf(s.dialog,sizeof(s.dialog),"%s",dialog);
    int fd=open(CONTROL_FILE,O_CREAT|O_TRUNC|O_RDWR|O_NOFOLLOW,0600);
    assert(fd>=0); assert(write(fd,&s,sizeof(s))==sizeof(s)); close(fd);
}
struct cue_test {
    const char *path,*name;
    int silence,ready,release;
    pthread_mutex_t lock;
    pthread_cond_t condition;
};
static void *read_cue_for_test(void *arg) {
    struct cue_test *test=arg;
    assert(prctl(PR_SET_NAME,test->name,0,0,0)==0);
    pthread_mutex_lock(&test->lock); test->ready=1;
    pthread_cond_signal(&test->condition);
    while (!test->release) pthread_cond_wait(&test->condition,&test->lock);
    pthread_mutex_unlock(&test->lock);
    unsigned char expected[65536],actual[65536];
    int fd=open(test->path,O_RDONLY); assert(fd>=0);
    ssize_t bytes=read(fd,expected,sizeof(expected)); assert(bytes>80 && bytes<(ssize_t)sizeof(expected)); close(fd);
    unsigned nonzero=0;
    for (ssize_t i=80;i<bytes;i++) nonzero|=expected[i];
    assert(nonzero); /* a zero-filled fixture would not prove cue isolation */
    FILE *file=fopen(test->path,"rb"); assert(file);
    assert((cue_file==file)==test->silence);
    assert(fread(actual,1,(size_t)bytes,file)==(size_t)bytes);
    assert(!memcmp(actual,expected,80));
    for (ssize_t i=80;i<bytes;i++) assert(actual[i]==(test->silence?0:expected[i]));
    assert(!fseek(file,80,SEEK_SET));
    assert(fread(actual,(size_t)bytes-80,1,file)==1); /* exact native call shape */
    for (ssize_t i=0;i<bytes-80;i++) assert(actual[i]==(test->silence?0:expected[i+80]));
    assert(fclose(file)==0); assert(!cue_file);
    fd=open(test->path,O_RDONLY); assert(fd>=0);
    assert(read(fd,actual,sizeof(actual))==bytes); close(fd);
    assert(!memcmp(actual,expected,(size_t)bytes)); /* backing file is unchanged */
    return arg;
}
static void cue_case(const char *path,const char *name,unsigned phase,unsigned after_create,int silence) {
    set_state_for_test(phase,"cue-test");
    struct cue_test test={.path=path,.name=name,.silence=silence,
        .lock=PTHREAD_MUTEX_INITIALIZER,.condition=PTHREAD_COND_INITIALIZER};
    pthread_t thread; assert(pthread_create(&thread,NULL,read_cue_for_test,&test)==0);
    pthread_mutex_lock(&test.lock);
    while (!test.ready) pthread_cond_wait(&test.condition,&test.lock);
    if (after_create) set_state_for_test(after_create,"cue-test");
    test.release=1; pthread_cond_signal(&test.condition); pthread_mutex_unlock(&test.lock);
    void *result=NULL; assert(pthread_join(thread,&result)==0); assert(result==&test);
    pthread_mutex_destroy(&test.lock); pthread_cond_destroy(&test.condition);
}
static void test_wake_cue(void) {
    const char *paths[]={"/usr/share/sound/wakeup_wozai.wav","/usr/share/sound/wakeup_ei_01.wav",
        "/usr/share/sound/wakeup_ei_02.wav","/usr/share/sound/wakeup_zai_01.wav","/usr/share/sound/wakeup_zai_02.wav"};
    role=1;
    for (unsigned i=0;i<5;i++) {
        cue_case(paths[i],"wakeup_tone_raw",IDLE,0,0);
        cue_case(paths[i],"wakeup_tone_raw",TRIGGERED,0,1);
    }
    cue_case(paths[0],"ordinary_audio",TRIGGERED,0,0);
    cue_case(paths[0],"wakeup_tone_raw",TRIGGERED,COMPLETE,1);
    cue_case(paths[0],"wakeup_tone_raw",TRIGGERED,FAILED,1);
    role=2; cue_case(paths[0],"wakeup_tone_raw",TRIGGERED,0,0); role=1;
    const char *other=CONTROL_DIR "/not-a-wake-cue.wav";
    unsigned char data[512]; memset(data,42,sizeof(data));
    int fd=open(other,O_CREAT|O_EXCL|O_WRONLY,0600); assert(fd>=0);
    assert(write(fd,data,sizeof(data))==sizeof(data)); close(fd);
    cue_case(other,"wakeup_tone_raw",TRIGGERED,0,0); assert(unlink(other)==0);
}
int main(void) {
    assert(mkdir(CONTROL_DIR,0700)==0);
    assert(dlopen("/usr/lib/libaivs_sdk.so",RTLD_NOW|RTLD_GLOBAL));
    assert(resolve_json()); role=2; json_ready=1;
    json_value event, array;
    header(&event,"SpeechRecognizer","Recognize","owned",1);
    j_ctor(&array,6); j_swap(j_member(&event,"context"),&array); j_dtor(&array);
    assert(asr_only(&event)); assert(asr_only(&event));
    const void *contexts=member(&event,"context");
    assert(j_size(contexts)==1); /* repeated serialization does not append duplicates */
    const void *control=j_index(contexts,0);
    assert(!strcmp(string_member(member(control,"header"),"namespace"),"Execution"));
    const void *disabled=member(member(control,"payload"),"disabled");
    assert(j_size(disabled)==2);
    assert(!strcmp(str_value(j_index(disabled,0)),"NLP"));
    assert(!strcmp(str_value(j_index(disabled,1)),"TTS"));
    j_dtor(&event);

    remember("owned"); set_state_for_test(BOUND,"owned");
    json_value instruction;
    header(&instruction,"Speaker","SetVolume","owned",0);
    assert(receive_json(1,&instruction)==0); j_dtor(&instruction);
    header(&instruction,"SpeechSynthesizer","Speak","owned",0);
    assert(receive_json(1,&instruction)==0); j_dtor(&instruction);
    header(&instruction,"MiotController","Operate","owned",0);
    assert(receive_json(1,&instruction)==0); j_dtor(&instruction);
    header(&instruction,"Speaker","SetVolume","ordinary-native",0);
    assert(receive_json(1,&instruction)==1); j_dtor(&instruction);
    for (unsigned i=0;i<3;i++) {
        const char *names[]={"Abort","TruncationNotification","Exception"};
        header(&instruction,"System",names[i],"owned",0);
        assert(receive_json(1,&instruction)==1); j_dtor(&instruction);
    }

    header(&instruction,"SpeechRecognizer","RecognizeResult","owned",0);
    void *payload=j_member(&instruction,"payload");
    json_value yes; j_ctor(&yes,5); /* Set through the exported bool constructor. */
    j_dtor(&yes);
    void (*bool_ctor)(void *,int)=dlsym(RTLD_NEXT,"_ZN4Json5ValueC1Eb"); assert(bool_ctor);
    bool_ctor(&yes,1); j_swap(j_member(payload,"is_final"),&yes); j_dtor(&yes);
    j_ctor(&array,6); json_value result; j_ctor(&result,7);
    put_string(&result,"text","什么时候去？\"原样\"\n第二行");
    j_append(&array,&result); j_dtor(&result); j_swap(j_member(payload,"results"),&array); j_dtor(&array);
    assert(receive_json(1,&instruction)==1);
    struct control s; int fd=state_open(&s); assert(fd>=0);
    assert(s.final_seen && !s.finished);
    assert(!strcmp(s.text,"什么时候去？\"原样\"\n第二行")); state_close(fd,NULL);

    set_state_for_test(BOUND,"next-dialog");
    assert(receive_json(1,&instruction)==0); /* delayed previous result cannot enter new turn */
    fd=state_open(&s); assert(fd>=0); assert(!s.final_seen && !s.text[0]); state_close(fd,NULL);
    j_dtor(&instruction);
    set_state_for_test(NATIVE_HANDOFF,"owned");
    const char *late_ns[]={"SpeechRecognizer","Dialog","System","MiotController"};
    const char *late_names[]={"StopCapture","Finish","Abort","Operate"};
    for (unsigned i=0;i<4;i++) {
        header(&instruction,late_ns[i],late_names[i],"owned",0);
        assert(receive_json(1,&instruction)==0); j_dtor(&instruction);
        header(&instruction,late_ns[i],late_names[i],"physical-native",0);
        assert(receive_json(1,&instruction)==1); j_dtor(&instruction);
    }
    header(&instruction,"Dialog","Finish","owned",0);
    set_state_for_test(RESULT,"owned"); fd=state_open(&s); assert(fd>=0); s.final_seen=1; state_close(fd,&s);
    assert(receive_json(1,&instruction)==1);
    fd=state_open(&s); assert(fd>=0); assert(s.phase==COMPLETE && s.finished); state_close(fd,NULL);
    /* Firmware parses Finish both for SDK bookkeeping and app dispatch. The
     * second parse, including after the CLI consumes the result, must still
     * reach the SDK or its TTS watchdog fires ten seconds after ASR final. */
    assert(receive_json(1,&instruction)==1);
    fd=state_open(&s); assert(fd>=0); s.phase=IDLE; state_close(fd,&s);
    assert(receive_json(1,&instruction)==1);
    fd=state_open(&s); assert(fd>=0); assert(s.phase==IDLE && s.finished); state_close(fd,NULL);
    fd=state_open(&s); assert(fd>=0); s.phase=NATIVE_HANDOFF; state_close(fd,&s);
    assert(receive_json(1,&instruction)==0); /* completed text can still be yielded */
    fd=state_open(&s); assert(fd>=0); s.phase=BOUND;
    strcpy(s.dialog,"new-native-dialog"); state_close(fd,&s);
    assert(receive_json(1,&instruction)==0);
    fd=state_open(&s); assert(fd>=0);
    assert(s.phase==BOUND && !strcmp(s.dialog,"new-native-dialog")); state_close(fd,NULL);
    j_dtor(&instruction);
    test_wake_cue();
    unlink(CONTROL_FILE); unlink(CONTROL_DIR "/events.log"); assert(rmdir(CONTROL_DIR)==0);
    puts("PASS: firmware JsonCpp ABI, ASR-only, duplicate serialization, action isolation, stale results, finish, owned cue PCM isolation (15 cases)");
    return 0;
}
