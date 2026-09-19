/* Independent ARM32 process. Fake audio/end callbacks only; no mic/cloud. */
#define CONTROL_DIR "/tmp/first_endpoint_unit"
#define NW_DIR CONTROL_DIR
#define NATIVE_BUSY_FILE CONTROL_DIR "/busy"
#define FAILURE_ARMED_FILE CONTROL_DIR "/failure-armed"
#define NATIVE_WAKE_DESTINATION CONTROL_DIR "/speech.sock"
#include "native_wake_probe.c"
#undef NDEBUG
#include <assert.h>
#include <sys/wait.h>
static unsigned stops,ends,delivered,wakes,expected_bytes;
static void *expected_pcm;
static struct neural_stream *observer_stream;
static struct neural_decision *observer_decision;
static char stream_path[256],decision_path[272];
static void fake_stop(void){stops++;}
static void fake_end(unsigned code){assert(code==4);ends++;}
static void fake_audio(void *ctx,void *pcm,unsigned n){assert(!ctx && pcm==expected_pcm && n==expected_bytes);delivered++;}
static void fake_wake(void *ctx,unsigned code,float angle){(void)ctx;(void)code;(void)angle;wakes++;}
static void native_phase(unsigned phase){
 struct control c={.magic=CONTROL_MAGIC,.version=1,.owner=getpid(),.deadline=now_ms()+30000,.phase=phase};
 int fd=open(CONTROL_FILE,O_CREAT|O_TRUNC|O_WRONLY,0600);assert(fd>=0);
 assert(write(fd,&c,sizeof(c))==sizeof(c));close(fd);
}
static void save(struct nw_state *s){
 int fd=open(NW_FILE,O_CREAT|O_TRUNC|O_WRONLY,0600);assert(fd>=0);
 assert(write(fd,s,sizeof(*s))==sizeof(*s));close(fd);
}
static void dispose(void){
 first_close(0);
 if(observer_stream){munmap(observer_stream,sizeof(*observer_stream));observer_stream=NULL;}
 if(observer_decision){munmap(observer_decision,sizeof(*observer_decision));observer_decision=NULL;}
 if(*stream_path)unlink(stream_path);if(*decision_path)unlink(decision_path);unlink(NW_FILE);
}
static struct nw_state fixture(unsigned nonce){
 dispose();native_phase(IDLE);role=1;
 struct nw_state s={.magic=NW_MAGIC,.owner=getpid(),.deadline=now_ms()+30000,.mode=1,.nonce=nonce,
 .observer=getpid(),.expected_producer=getpid(),.expected_consumer=getpid(),.wake_ms=now_ms()};
 nw_stream_path(stream_path,sizeof(stream_path),&s);snprintf(decision_path,sizeof(decision_path),"%s.decision",stream_path);
 int fd=open(stream_path,O_CREAT|O_EXCL|O_RDWR,0600);assert(fd>=0);assert(!ftruncate(fd,sizeof(*observer_stream)));
 observer_stream=mmap(NULL,sizeof(*observer_stream),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);close(fd);assert(observer_stream!=MAP_FAILED);
 ns_init(observer_stream,nonce,s.owner,s.observer);
 fd=open(decision_path,O_CREAT|O_EXCL|O_RDWR,0600);assert(fd>=0);assert(!ftruncate(fd,sizeof(*observer_decision)));
 observer_decision=mmap(NULL,sizeof(*observer_decision),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);close(fd);assert(observer_decision!=MAP_FAILED);
 nd_init(observer_decision,nonce,s.owner,s.observer);
 assert(first_claim(&s));s.prepared=1;s.producer=s.consumer=getpid();s.phase=NW_BOUND;strcpy(s.dialog,"first-owned");
 save(&s);return s;
}
static void proposal(unsigned frames,unsigned age){
 nd_publish(observer_decision,(struct neural_proposal){getpid(),frames,frames,now_ms()-age,0});
}
static void feed(unsigned char *pcm,unsigned bytes){
 expected_pcm=pcm;expected_bytes=bytes;first_pcm(NULL,pcm,bytes);
}
static void boolean(void *v,const char *key,int b){
 void (*ctor)(void *,int)=dlsym(RTLD_NEXT,"_ZN4Json5ValueC1Eb");assert(ctor);
 json_value x;ctor(&x,b);j_swap(j_member(v,key),&x);j_dtor(&x);
}
static void instruction(json_value *v,const char *name,const char *id){
 j_ctor(v,7);void *h=j_member(v,"header");put_string(h,"namespace","SpeechRecognizer");put_string(h,"name",name);put_string(h,"dialog_id",id);
}
static size_t pack_prepare(unsigned char *out) {
 uint32_t top[6],up[9],prep[6];
 void (*init)(void *)=dlsym(RTLD_NEXT,"speech_message__init");assert(init);init(top);
 init=dlsym(RTLD_NEXT,"speech_message__upward_message__init");assert(init);init(up);
 init=dlsym(RTLD_NEXT,"speech_message__upward_message__stream_prepare_request_message__init");assert(init);init(prep);
 top[3]=0;top[4]=(uint32_t)(uintptr_t)up;up[3]=1;up[5]=(uint32_t)(uintptr_t)prep;prep[3]=0;
 return speech_message__pack(top,out);
}
static struct nw_state tag_fixture(unsigned nonce) {
 struct nw_state s=fixture(nonce);first_close(0);ns_init(observer_stream,s.nonce,s.owner,s.observer);
 s.mode=3;s.phase=NW_ARMED;s.prepared=0;s.producer=s.consumer=0;s.accepted=0;s.dialog[0]=0;
 memset(s.tag,(int)nonce,sizeof(s.tag));save(&s);first_wake(NULL,1,0);
 int fd=nw_open(&s);assert(fd>=0 && s.prepared && s.mode==3 && s.phase==NW_WAKE);nw_close(fd,NULL);
 return s;
}
static void tagged_transport_test(void) {
 assert(dlopen("/usr/lib/libaivs-message-util.so",RTLD_NOW|RTLD_GLOBAL));
 int receiver=socket(AF_UNIX,SOCK_DGRAM,0),sender=socket(AF_UNIX,SOCK_DGRAM,0);assert(receiver>=0 && sender>=0);
 struct sockaddr_un address={.sun_family=AF_UNIX};strcpy(address.sun_path,NATIVE_WAKE_DESTINATION);
 assert(!bind(receiver,(const struct sockaddr *)&address,sizeof(address)));
 struct timeval timeout={.tv_sec=1};assert(!setsockopt(receiver,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)));
 unsigned char raw[284],wire[284],old[284];size_t old_size=0;
 /* Same raw prepare twice, same native process lifetime, distinct tokens. */
 for(unsigned round=0;round<2;round++){
  struct nw_state s=tag_fixture(31+round);memset(raw,0xa5,sizeof(raw));size_t n=pack_prepare(raw);assert(n==10);
  for(size_t i=n;i<sizeof(raw);i++)assert(raw[i]==0xa5); /* caller buffer unextended */
  assert(sendto(sender,raw,n,0,(const struct sockaddr *)&address,sizeof(address))==(ssize_t)n);
  ssize_t got=recv(receiver,wire,sizeof(wire),0);assert(got==(ssize_t)(n+NW_TAG_OVERHEAD));
  unsigned char tag[NW_TAG_BYTES];assert(nw_tag_extract(wire,got,tag)==n && !memcmp(tag,s.tag,sizeof(tag)));
  if(!round){memcpy(old,wire,got);old_size=(size_t)got;}
  else assert(!memcmp(old,wire,n) && memcmp(old+n,wire+n,NW_TAG_OVERHEAD));
  /* A receiver without our hook accepts the extension as an unknown field. */
  void *(*unpack)(void *,size_t,const void *)=dlsym(RTLD_NEXT,"speech_message__unpack");
  void (*free_message)(void *,void *)=dlsym(RTLD_NEXT,"speech_message__free_unpacked");
  void *msg=unpack(NULL,got,wire);assert(msg);free_message(msg,NULL);
  role=2;msg=speech_message__unpack(NULL,got,wire);assert(msg && first_message==msg);
  int fd=nw_open(&s);assert(fd>=0 && s.accepted);nw_close(fd,NULL);
  speech_message__free_unpacked(msg,NULL);assert(!first_message);
  if(round){
   msg=speech_message__unpack(NULL,old_size,old);assert(msg && !first_message);
   assert(nw_open(&s)<0);speech_message__free_unpacked(msg,NULL);
  }
 }
 /* An old same-content datagram must never acquire a newly armed generation. */
 struct nw_state s=tag_fixture(33);size_t n=pack_prepare(raw);assert(n==10);
 role=2;void *msg=speech_message__unpack(NULL,old_size,old);assert(msg && !first_message && nw_open(&s)<0);speech_message__free_unpacked(msg,NULL);
 /* Untagged / duplicate prepare revokes control rather than guessing. */
 s=tag_fixture(34);n=pack_prepare(raw);role=2;msg=speech_message__unpack(NULL,n,raw);assert(msg && !first_message && nw_open(&s)<0);speech_message__free_unpacked(msg,NULL);
 s=tag_fixture(35);n=pack_prepare(raw);size_t got=nw_tag_append(wire,sizeof(wire),raw,n,s.tag);role=2;
 msg=speech_message__unpack(NULL,got,wire);assert(msg && first_message);speech_message__free_unpacked(msg,NULL);
 msg=speech_message__unpack(NULL,got,wire);assert(msg && !first_message && nw_open(&s)<0);speech_message__free_unpacked(msg,NULL);
 close(sender);close(receiver);unlink(NATIVE_WAKE_DESTINATION);role=1;
}
static void route_test(void) {
 struct nw_state s=fixture(71);strcpy(s.dialog,"journal-case");memset(s.tag,71,sizeof(s.tag));
 assert(nr_begin(&s));assert(!nr_finish(&s,1));
 s.modified=s.ended=s.final_seen=s.finished=1;s.end_reason=1;
 assert(nr_complete(&s,1) && !nr_complete(&s,0));
 s.end_reason=2;assert(!nr_complete(&s,1) && !nr_finish(&s,1));s.end_reason=1;
 s.failed=1;assert(!nr_complete(&s,1));s.failed=0;
 s.final_seen=0;assert(!nr_complete(&s,1));s.final_seen=1;
 s.finished=0;assert(!nr_complete(&s,1));s.finished=1;
 s.phase=NW_CANCELLED;assert(!nr_complete(&s,1));s.phase=NW_BOUND;
 s.tag[0]++;assert(!nr_finish(&s,1));s.tag[0]--;
 assert(nr_finish(&s,0));assert(!nr_finish(&s,1)); /* failed is terminal */
 assert(!nr_begin(&s));unlink(NW_ROUTE_DIR "/journal-case");
 assert(nr_begin(&s));assert(nr_finish(&s,1));
 int fd=open(NW_ROUTE_DIR "/journal-case",O_RDONLY);char record[128];assert(fd>=0 && nr_read(fd,record,sizeof(record)));close(fd);assert(strstr(record," quiet\n"));
 unlink(NW_ROUTE_DIR "/journal-case");
 assert(!symlink("missing",NW_ROUTE_DIR "/journal-case"));assert(!nr_begin(&s) && !nr_finish(&s,1));unlink(NW_ROUTE_DIR "/journal-case");
 strcpy(s.dialog,"../escape");assert(!nr_begin(&s));
 strcpy(s.dialog,"journal-case");assert(nr_begin(&s));
 /* Disposing the controller and its audio must not erase pending evidence. */
 dispose();fd=open(NW_ROUTE_DIR "/journal-case",O_RDONLY);assert(fd>=0 && nr_read(fd,record,sizeof(record)));close(fd);assert(strstr(record," pending\n"));
 unlink(NW_ROUTE_DIR "/journal-case");unlink(NW_ROUTE_DIR "/first-owned");assert(!rmdir(NW_ROUTE_DIR));
}
static void no_speech_test(void) {
 struct nw_state s=fixture(79);strcpy(s.dialog,"no-speech-case");s.modified=1;save(&s);assert(nr_begin(&s));
 unsigned before=ends;unsigned char pcm[320]={0};
 for(unsigned i=0;i<ND_START_FRAMES;i++)feed(pcm,sizeof(pcm));
 nd_publish(observer_decision,(struct neural_proposal){getpid(),ND_START_FRAMES,ND_NO_SPEECH,now_ms(),0});
 first_end_step();assert(ends==before+1);
 int fd=nw_open(&s);assert(fd>=0 && s.ended && !s.failed && s.end_reason==NW_END_NO_SPEECH);
 s.final_seen=s.finished=1;nw_close(fd,&s);
 assert(!nr_complete(&s,1) && !nr_finish(&s,1));assert(nr_finish(&s,0));
 first_end_step();assert(ends==before+1);
 unlink(NW_ROUTE_DIR "/no-speech-case");assert(!rmdir(NW_ROUTE_DIR));
 puts("PASS no speech: owned EOF once, never quiet or LLM route");
}
static void helper_death_test(void) {
 struct nw_state s=fixture(80);strcpy(s.dialog,"helper-died");
 pid_t helper=fork();assert(helper>=0);if(!helper){for(;;)pause();}
 s.observer=helper;s.modified=1;observer_stream->observer=helper;observer_decision->observer=helper;
 save(&s);assert(nr_begin(&s));
 assert(!kill(helper,SIGKILL));int status;assert(waitpid(helper,&status,0)==helper && WIFSIGNALED(status));
 unsigned before=ends;unsigned char pcm[320]={0};feed(pcm,sizeof(pcm));first_end_step();
 assert(ends==before+1);
 int fd=nw_open(&s);assert(fd>=0 && s.failed && s.ended && s.end_reason==3);
 s.final_seen=s.finished=1;nw_close(fd,&s);
 assert(!nr_complete(&s,1) && !nr_finish(&s,1));assert(nr_finish(&s,0));
 /* A new generation in the same test/native process can still finish. */
 s=fixture(81);strcpy(s.dialog,"after-helper-death");s.modified=1;save(&s);assert(nr_begin(&s));
 feed(pcm,sizeof(pcm));proposal(1,0);first_end_step();assert(ends==before+2);
 fd=nw_open(&s);assert(fd>=0 && !s.failed && s.end_reason==1);
 s.final_seen=s.finished=1;nw_close(fd,&s);assert(nr_finish(&s,1));
 unlink(NW_ROUTE_DIR "/helper-died");unlink(NW_ROUTE_DIR "/after-helper-death");assert(!rmdir(NW_ROUTE_DIR));
 puts("PASS helper death: forced EOF denied; next generation quiet succeeds");
}
static void replacement_test(void) {
 struct nw_state s=fixture(90);strcpy(s.dialog,"interrupted-case");
 s.modified=1;save(&s);assert(nr_begin(&s));
 unsigned char pcm[320]={0};feed(pcm,sizeof(pcm));proposal(1,0);
 unsigned before=ends;first_wake(NULL,1,90);first_end_step();assert(ends==before);
 role=2;json_value v;instruction(&v,"RecognizeResult","interrupted-case");
 boolean(j_member(&v,"payload"),"is_final",1);first_instruction(&v);j_dtor(&v);
 instruction(&v,"Finish","interrupted-case");
 put_string(j_member(&v,"header"),"namespace","Dialog");first_instruction(&v);j_dtor(&v);role=1;
 int fd=open(NW_FILE,O_RDONLY);assert(fd>=0 && read(fd,&s,sizeof(s))==sizeof(s));close(fd);
 assert(s.phase==NW_CANCELLED && s.end_reason==NW_END_REPLACED && !s.ended && !s.final_seen && !s.finished);
 assert(observer_stream->state==NS_INVALID && !first_local_owned && !nr_complete(&s,1));
 char record[128];fd=open(NW_ROUTE_DIR "/interrupted-case",O_RDONLY);
 assert(fd>=0 && nr_read(fd,record,sizeof(record)));close(fd);assert(strstr(record," pending\n"));
 unlink(NW_ROUTE_DIR "/interrupted-case");assert(!rmdir(NW_ROUTE_DIR));
 puts("PASS replacement: no old EOF; late final/Finish ignored; pending retained");
}
static void pool_handoff_test(unsigned total){
 dispose();native_phase(IDLE);role=1;
 struct np_pool pool={.magic=NP_MAGIC,.owner=getpid(),.observer=getpid(),.count=NP_MAX,.ready=1,.deadline=now_ms()+30000};
 pool.rolling_limit=total>NP_MAX?total:0;
 struct nw_state plans[12];assert(total<=12);
 struct neural_stream *streams[12];struct neural_decision *decisions[12];
 for(unsigned i=0;i<total;i++){
  struct nw_state *s=&plans[i];
  *s=(struct nw_state){.magic=NW_MAGIC,.owner=getpid(),.observer=getpid(),.deadline=pool.deadline,
   .mode=3,.nonce=100+i,.phase=NW_ARMED,.expected_producer=getpid(),.expected_consumer=getpid()};
  memset(s->tag,(int)(100+i),NW_TAG_BYTES);
  if(i<NP_MAX){pool.slot[i].plan=*s;pool.slot[i].prepared=1;}
  char path[280];np_path(path,sizeof(path),s,"");streams[i]=np_map(path,sizeof(*streams[i]),1,1);assert(streams[i]);
  ns_init(streams[i],s->nonce,s->owner,s->observer);
  np_path(path,sizeof(path),s,".decision");decisions[i]=np_map(path,sizeof(*decisions[i]),1,1);assert(decisions[i]);
  nd_init(decisions[i],s->nonce,s->owner,s->observer);
 }
 assert(np_valid(&pool));int pf=open(NP_FILE,O_CREAT|O_EXCL|O_RDWR,0600);assert(pf>=0);
 assert(write(pf,&pool,sizeof(pool))==sizeof(pool));close(pf);save(&pool.slot[0].plan);
 unsigned before=ends;unsigned char pcm[320]={0};struct nw_state previous={0};
 for(unsigned i=0;i<total;i++){
  if(i>=NP_MAX){
   pf=np_read_locked(NP_FILE,&pool,sizeof(pool));assert(pf>=0 && np_valid(&pool));
   unsigned index=i%NP_MAX;assert(pool.active!=index && pool.slot[index].status);
   assert(streams[i-NP_MAX]->state==NS_INVALID);
   pool.slot[index]=(struct np_slot){.plan=plans[i],.prepared=1};
   assert(np_valid(&pool) && pwrite(pf,&pool,sizeof(pool),0)==sizeof(pool));close(pf);
  }
  first_wake(NULL,1,0);struct nw_state s;int fd=nw_open(&s);assert(fd>=0);
  assert(s.nonce==100+i && s.phase==NW_WAKE && s.prepared && s.producer==(unsigned)getpid());
  assert(streams[i]->state==NS_LIVE && !streams[i]->used);
  if(i>=NP_MAX){
   nd_publish(decisions[i-NP_MAX],(struct neural_proposal){getpid(),1,1,now_ms(),0});
   assert(!nd_due(streams[i],decisions[i-NP_MAX],s.nonce,s.owner,getpid(),now_ms()));
   first_message=(void *)1;first_owner=s.owner;first_deadline=s.deadline;first_nonce=plans[i-NP_MAX].nonce;
   assert(!first_scoped(&s));first_message=NULL;
  }
  if(i){
   assert(streams[i-1]->state==NS_INVALID);
   assert(!nd_due(streams[i],decisions[i-1],s.nonce,s.owner,getpid(),now_ms()));
   first_message=(void *)1;first_owner=s.owner;first_deadline=s.deadline;first_nonce=previous.nonce;
   assert(!first_scoped(&s));first_nonce=s.nonce;assert(first_scoped(&s));first_message=NULL;
  }
  s.phase=NW_BOUND;s.consumer=getpid();s.accepted=s.modified=s.wake_modified=1;
  snprintf(s.dialog,sizeof(s.dialog),"pool-%u",i);assert(nr_begin(&s));nw_close(fd,&s);
  feed(pcm,320);nd_publish(decisions[i],(struct neural_proposal){getpid(),1,1,now_ms(),0});
  if(i){
   role=2;json_value v;instruction(&v,"RecognizeResult",previous.dialog);boolean(j_member(&v,"payload"),"is_final",1);first_instruction(&v);j_dtor(&v);role=1;
   fd=nw_open(&s);assert(fd>=0 && !s.final_seen);nw_close(fd,NULL);
  }
  previous=s;
 }
 first_wake(NULL,1,0);first_end_step();assert(ends==before && !first_stream && !first_local_owned);
 pf=np_read_locked(NP_FILE,&pool,sizeof(pool));assert(pf>=0 && !pool.ready);close(pf);
 for(unsigned i=0;i<total;i++){
  if(i<NP_MAX){
   assert(pool.slot[i].status==NP_RETIRED_REPLACED && pool.slot[i].retired.phase==NW_CANCELLED);
   assert(!nr_complete(&pool.slot[i].retired,1));
  }
  char path[280],record[128];
  snprintf(path,sizeof(path),NW_ROUTE_DIR "/pool-%u",i);int fd=open(path,O_RDONLY);assert(fd>=0 && nr_read(fd,record,sizeof(record)));close(fd);
  assert(strstr(record," pending\n"));unlink(path);
  munmap(streams[i],sizeof(*streams[i]));munmap(decisions[i],sizeof(*decisions[i]));
  np_path(path,sizeof(path),&plans[i],"");unlink(path);
  np_path(path,sizeof(path),&plans[i],".decision");unlink(path);
 }
 assert(!rmdir(NW_ROUTE_DIR));unlink(NP_FILE);unlink(NW_FILE);
 printf("PASS pool handoff: turns=%u; old proposals/scope/final denied after wrap; no cancelled EOF\n",total);
}
int main(void){
 assert(mkdir(CONTROL_DIR,0700)==0);
 assert(dlopen("/usr/lib/libaivs_sdk.so",RTLD_NOW|RTLD_GLOBAL));assert(resolve_json());json_ready=1;
 first_end=fake_end;first_stop=fake_stop;first_asr=fake_audio;first_worker_ready=1;first_chained=fake_wake;
 struct nw_state s=fixture(1);
 role=2;json_value w;j_ctor(&w,7);boolean(j_member(&w,"payload"),"enable_natural_record_v2",1);
 put_string(j_member(j_member(&w,"payload"),"wakeup_info"),"word","小爱同学");
 assert(first_modify_wakeup(&w,&s));assert(j_bool(member(member(&w,"payload"),"enable_natural_record_v2")));
 s.mode=2;s.phase=NW_DIALOG;s.prepared=0;assert(!first_modify_wakeup(&w,&s));s.prepared=1;
 assert(first_modify_wakeup(&w,&s) && s.wake_modified);
 assert(!j_bool(member(member(&w,"payload"),"enable_natural_record_v2")));
 assert(!strcmp(string_member(member(member(&w,"payload"),"wakeup_info"),"word"),"小爱同学"));
 j_dtor(&w);s.phase=NW_BOUND;
 json_value v;j_ctor(&v,7);put_string(j_member(&v,"context"),"sentinel","native-context");
 put_string(j_member(j_member(&v,"payload"),"tts"),"vendor","AiNiRobot");
 boolean(j_member(j_member(&v,"payload"),"asr"),"vad",1);
 role=2;s.observer=1;assert(!first_modify(&v,&s));assert(j_bool(member(member(member(&v,"payload"),"asr"),"vad")));
 s.observer=getpid();assert(first_modify(&v,&s));assert(s.modified);
 assert(!j_bool(member(member(member(&v,"payload"),"asr"),"vad")));
 assert(j_bool(member(member(&v,"payload"),"is_using_local_vad")));
 assert(!strcmp(string_member(member(&v,"context"),"sentinel"),"native-context"));
 assert(!strcmp(string_member(member(member(&v,"payload"),"tts"),"vendor"),"AiNiRobot"));
 j_dtor(&v);save(&s);role=1;
 unsigned char pcm[640];memset(pcm,73,sizeof(pcm));feed(pcm,320);assert(delivered==1 && observer_stream->used==320 && observer_stream->pcm[0]==73);
 proposal(1,151);first_end_step();assert(!ends);
 proposal(1,0);feed(pcm,320);first_end_step();assert(!ends); /* never end with unread audio */
 proposal(2,0);first_end_step();assert(ends==1 && stops==1 && observer_stream->state==NS_DONE);
 first_end_step();assert(ends==1);
 int fd=nw_open(&s);assert(fd>=0 && s.ended && s.end_reason==1);nw_close(fd,NULL);
 s=fixture(2);s.modified=1;save(&s);feed(pcm,320);proposal(1,0);
 first_wake(NULL,1,90);assert(wakes==1 && observer_stream->state==NS_INVALID);first_end_step();assert(ends==1);
 s=fixture(3);s.modified=1;save(&s);feed(pcm,320);proposal(1,0);
 first_wake(NULL,0x101,0);assert(wakes==2 && observer_stream->state==NS_LIVE);first_end_step();assert(ends==2);
 s=fixture(4);s.modified=1;save(&s);feed(pcm,320);ns_close(observer_stream,0);first_end_step();assert(ends==3);
 fd=nw_open(&s);assert(fd>=0 && s.failed && s.end_reason==3);nw_close(fd,NULL);
 s=fixture(5);s.modified=1;save(&s);feed(pcm,320);proposal(1,0);native_phase(REQUEST);first_end_step();assert(ends==3);native_phase(IDLE);
 s=fixture(6);s.modified=1;save(&s);feed(pcm,320);proposal(1,0);
 role=2;instruction(&v,"StopCapture","unrelated");first_instruction(&v);j_dtor(&v);role=1;
 fd=nw_open(&s);assert(fd>=0 && !s.ended);nw_close(fd,NULL);
 role=2;instruction(&v,"RecognizeResult",s.dialog);boolean(j_member(&v,"payload"),"is_final",1);first_instruction(&v);j_dtor(&v);role=1;
 first_end_step();assert(ends==3 && !first_stream);
 s=fixture(7);s.modified=1;s.wake_ms=now_ms()-20001;save(&s);feed(pcm,320);first_end_step();assert(ends==4);
 fd=nw_open(&s);assert(fd>=0 && s.end_reason==2);nw_close(fd,NULL);
 s=fixture(8);s.modified=1;save(&s);feed(pcm,319);first_end_step();assert(ends==5 && delivered==9);
 s=fixture(9);s.modified=1;save(&s);feed(pcm,320);proposal(1,0);unlink(NW_FILE);first_end_step();assert(ends==5);
 assert(__atomic_load_n(&first_local_owned,__ATOMIC_ACQUIRE)==9);first_wake(NULL,1,0);assert(!first_local_owned);
 for(unsigned prior=0;prior<3;prior++){
     s=fixture(10+prior);first_close(0);ns_init(observer_stream,s.nonce,s.owner,s.observer);
     s.phase=NW_ARMED;s.prepared=0;s.producer=s.consumer=0;save(&s);
     first_normal_wakes=prior==1?1:0;first_prepare_sent=prior==2?1:0;
     first_wake(NULL,1,90);
     fd=nw_open(&s);assert(fd>=0);nw_close(fd,NULL);
     if(!prior)assert(s.prepared && s.mode==1 && first_stream && observer_stream->state==NS_LIVE);
     else assert(!s.prepared && !s.mode && !first_stream && observer_stream->state==NS_WAIT);
 }
 tagged_transport_test();
 route_test();
 no_speech_test();helper_death_test();
 replacement_test();
 pool_handoff_test(NP_MAX);pool_handoff_test(12);
 dispose();unlink(CONTROL_FILE);unlink(CONTROL_DIR "/events.log");assert(!rmdir(CONTROL_DIR));
 puts("PASS first endpoint: native JSON retained; raw PCM; fresh/caught-up candidate; second wake; suspect callback; helper failure; ASR collision; final; cap; revoked owner");
 return 0;
}
