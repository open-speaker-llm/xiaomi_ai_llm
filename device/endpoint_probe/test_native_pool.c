/* Controller integration fixture only; no model, microphone, cloud or SDK. */
#include "native_pool_maps.h"
#include "native_route.h"
#undef NDEBUG
#include <assert.h>
#include <stdlib.h>
static void put(const char *path,const void *data,size_t size){
 int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC,0600);assert(fd>=0 && write(fd,data,size)==(ssize_t)size);close(fd);
}
int main(int argc,char **argv){
 assert(argc>=2);setvbuf(stdout,NULL,_IOLBF,0);
 if(!strcmp(argv[1],"init")){
  assert(argc==3);unsigned pid=(unsigned)strtoul(argv[2],NULL,10);assert(alive(pid));
  struct control c={.magic=CONTROL_MAGIC,.version=1,.mipns_pid=pid,.aivs_pid=pid};put(CONTROL_FILE,&c,sizeof(c));return 0;
 }
 if(!strcmp(argv[1],"helper")){
  struct np_pool p;int fd=np_read_locked(NP_FILE,&p,sizeof(p));assert(fd>=0 && np_valid(&p));close(fd);
  assert(p.observer==(unsigned)getpid() && p.owner==(unsigned)getppid());
  const char *stage=getenv("POOL_STAGE");puts("POOL_FIXTURE_STARTED");
  if(stage && !strcmp(stage,"before")){while(alive(p.owner) && getppid()==(pid_t)p.owner)usleep(10000);return 1;}
  struct np_view views[NP_MAX]={0};
  for(unsigned i=0;i<p.count;i++)assert(np_view_create(&views[i],&p.slot[i].plan));
  puts("POOL_FIXTURE_MAPPED");
  while(alive(p.owner) && getppid()==(pid_t)p.owner){
   struct np_pool current;int state=np_read_locked(NP_FILE,&current,sizeof(current));
   assert(state>=0);close(state);assert(np_valid(&current));
   if(!current.ready && current.retired_total)return 0;
   if(stage && !strcmp(stage,"refill") && current.slot[0].recycling){
    puts("POOL_FIXTURE_REFILL_PAUSED");
    while(alive(p.owner) && getppid()==(pid_t)p.owner)usleep(10000);return 1;
   }
   assert(np_refresh_views(views,&current));p=current;
   for(unsigned i=0;i<p.count;i++){
    struct neural_stream *s=views[i].stream;struct neural_receipt *q=views[i].receipt;
    unsigned status=__atomic_load_n(&s->state,__ATOMIC_ACQUIRE);
    if(status==NS_DONE || status==NS_INVALID){
     q->frames=s->used/320;
     __atomic_store_n(&q->status,status==NS_DONE?NQ_COMPLETE:NQ_INVALID,__ATOMIC_RELEASE);
    }
   }
   usleep(2000);
  }
  return 1;
 }
 if(!strcmp(argv[1],"feed")){
  assert(argc==4);struct nw_state s;int fd=nw_open(&s);assert(fd>=0 && s.phase==NW_BOUND);nw_close(fd,NULL);
  char path[280];np_path(path,sizeof(path),&s,"");struct neural_stream *stream=np_map(path,sizeof(*stream),0,1);assert(stream);
  np_path(path,sizeof(path),&s,".decision");struct neural_decision *decision=np_map(path,sizeof(*decision),0,0);assert(decision);
  FILE *audio=fopen(argv[2],"rb");assert(audio);unsigned char pcm[320];uint32_t start=now_ms(),frames=0;
  int cancel=!strcmp(argv[3],"cancel"),empty=!strcmp(argv[3],"empty"),burst=!strcmp(argv[3],"burst");
  int overload=!strcmp(argv[3],"overload");
  while(fread(pcm,1,320,audio)==320){
   assert(ns_append(stream,pcm,320));frames++;
   /* Lossless native delivery can arrive in a burst after scheduling delay. */
   if(burst && frames>=151 && frames<181)continue;
   if(overload && frames>=151 && frames<211)continue;
   while((int32_t)(start+frames*10-now_ms())>0)usleep(1000);
   if(cancel && frames==100)break;
  }
  fclose(audio);
  for(unsigned i=0;!cancel && !overload && i<100 && !nd_end_due(stream,decision,s.nonce,s.owner,s.producer,now_ms(),empty);i++)usleep(2000);
  fd=nw_open(&s);assert(fd>=0);s.frames=stream->used/320;
  if(cancel){ns_close(stream,0);assert(np_advance(&s,NP_RETIRED_REPLACED));}
  else if(overload){struct neural_proposal p;assert(nd_read(decision,&p) && p.invalid);
   assert(!nd_due(stream,decision,s.nonce,s.owner,s.producer,now_ms()));
   s.ended=s.final_seen=s.finished=s.failed=1;s.end_reason=3;ns_close(stream,0);}
  else {assert(nd_end_due(stream,decision,s.nonce,s.owner,s.producer,now_ms(),empty));
   s.ended=s.final_seen=s.finished=1;s.end_reason=empty?NW_END_NO_SPEECH:1;ns_close(stream,1);}
  nw_close(fd,&s);printf("POOL_FEED frames=%u cancelled=%d\n",frames,cancel);return 0;
 }
 struct nw_state s;int fd=np_read_locked(NW_FILE,&s,sizeof(s));assert(fd>=0);
 if(!strcmp(argv[1],"begin") || !strcmp(argv[1],"start")){
  assert(s.phase==NW_ARMED);s.prepared=s.accepted=s.modified=s.wake_modified=1;s.phase=NW_BOUND;
  s.producer=s.expected_producer;s.consumer=s.expected_consumer;s.wake_ms=now_ms();s.frames=!strcmp(argv[1],"begin");
  snprintf(s.dialog,sizeof(s.dialog),"pool-%u",s.nonce);assert(nr_begin(&s));
  char path[280];np_path(path,sizeof(path),&s,"");struct neural_stream *stream=np_map(path,sizeof(*stream),0,1);assert(stream);
  unsigned char pcm[320]={0};assert(ns_claim(stream,s.nonce,s.owner,s.producer));if(s.frames)assert(ns_append(stream,pcm,320));
 }else if(!strcmp(argv[1],"bypass")){
  assert(s.phase==NW_ARMED);char path[280];np_path(path,sizeof(path),&s,"");
  struct neural_stream *stream=np_map(path,sizeof(*stream),0,1);assert(stream && stream->state==NS_WAIT);
  s.phase=NW_WAKE;s.mode=0;s.producer=s.expected_producer;s.wake_ms=now_ms();
  assert(np_advance(&s,NP_RETIRED_REPLACED));
  assert(stream->state==NS_INVALID); /* A skipped capture must not stall the shared helper. */
 }else if(!strcmp(argv[1],"complete")){
  assert(s.phase==NW_BOUND);s.ended=s.final_seen=s.finished=s.end_reason=1;
  char path[280];np_path(path,sizeof(path),&s,"");struct neural_stream *stream=np_map(path,sizeof(*stream),0,1);assert(stream);ns_close(stream,1);
 }else if(!strcmp(argv[1],"cancel")){
  assert(s.phase==NW_BOUND);char path[280];np_path(path,sizeof(path),&s,"");struct neural_stream *stream=np_map(path,sizeof(*stream),0,1);assert(stream);ns_close(stream,0);
  assert(np_advance(&s,NP_RETIRED_REPLACED));
 }else if(!strcmp(argv[1],"assert-ready")){
  assert(s.phase==NW_ARMED && s.mode==3 && alive(s.observer));printf("nonce=%u owner=%u observer=%u\n",s.nonce,s.owner,s.observer);close(fd);return 0;
 }else assert(0);
 assert(pwrite(fd,&s,sizeof(s),0)==sizeof(s));close(fd);return 0;
}
