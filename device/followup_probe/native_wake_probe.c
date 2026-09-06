#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
/* Temporary, firmware-gated observation and single-shot callback probe.
 * xaudio_register_callback's three used args and hard-float callback ABI
 * are from the matching ARM32 library disassembly. No patch of code/data. */
typedef void (*wake_fn)(void*,unsigned,float);
typedef void *(*register_fn)(void*,wake_fn,void*);
static register_fn real_register;
static wake_fn original_wake;
static void *wake_context;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static unsigned last_code,seen,attempts;
static float last_angle;
static void note(const char*,...);
static time_t begin;
static time_t auto_at;
static float auto_angle;
static time_t record_until;
static int record_fd=-1;
static time_t nonwake_until;
typedef void (*ivw_fn)(unsigned,void*,unsigned,unsigned,int);
static ivw_fn original_ivw;
typedef void (*asr_fn)(void*,void*,unsigned);
static asr_fn original_asr;
static unsigned char *replay;
static size_t replay_size,replay_cursor;
static time_t replay_until;
static unsigned asr_frames;
static void asr_observed(void *ctx,void *buffer,unsigned size) {
 if(!original_asr)return;
 if(record_until>=time(NULL) && record_fd>=0 && size<=8192)(void)write(record_fd,buffer,size);
 if(asr_frames%25==0 && size>=2 && size<=8192){long total=0;int peak=0;const int16_t *pcm=buffer;for(unsigned j=0;j<size/2;j++){int v=pcm[j];if(v<0)v=-v;total+=v;if(v>peak)peak=v;}note("AUDIO mean_abs=%ld peak=%d",total/(size/2),peak);}
 if(replay && replay_until>=time(NULL) && replay_cursor<replay_size && size<=8192) {
  unsigned char audio[8192]={0};size_t take=replay_size-replay_cursor;if(take>size)take=size;
  memcpy(audio,replay+replay_cursor,take);replay_cursor+=take;
  original_asr(ctx,audio,size);
 } else original_asr(ctx,buffer,size);
 if(++asr_frames==1 || asr_frames%50==0)note("ASR_FRAMES count=%u size=%u replay=%u/%u",asr_frames,size,(unsigned)replay_cursor,(unsigned)replay_size);
}
typedef int (*upload_register_fn)(void*,ivw_fn,void*,unsigned,unsigned);
int register_data_upload_callback(void *asr,ivw_fn ivw,void *ctx,unsigned mode,unsigned flag) {
 upload_register_fn fn=(upload_register_fn)dlsym(RTLD_NEXT,"register_data_upload_callback");
 original_ivw=ivw;original_asr=(asr_fn)asr;note("UPLOAD_REGISTER ivw=%p",(void*)ivw);
 return fn?fn((void*)asr_observed,ivw,ctx,mode,flag):-1;
}
typedef size_t (*pack_fn)(const void*,void*);
size_t speech_message__pack(const void *message,void *output) {
 pack_fn fn=(pack_fn)dlsym(RTLD_NEXT,"speech_message__pack");
 const uint32_t *top=message;
 if(!fn)return 0;
 if(nonwake_until>=time(NULL) && top && top[3]==0 && top[4]) {
  uint32_t *up=(uint32_t*)(uintptr_t)top[4];
  if(up[3]==1 && up[5]) {
   uint32_t *prepare=(uint32_t*)(uintptr_t)up[5];
   uint32_t old=prepare[3];prepare[3]=1;
   size_t n=fn(message,output);prepare[3]=old;
   note("PREPARE override activate_mode %u -> NONWAKEUP(1)",old);return n;
  }
 }
 return fn(message,output);
}
static __thread int synthetic;
static void note(const char *format,...) {
 char buf[512];va_list args;va_start(args,format);
 int n=snprintf(buf,sizeof(buf),"%ld ",(long)time(NULL));
 int m=vsnprintf(buf+n,sizeof(buf)-(size_t)n,format,args);va_end(args);
 if(m<0)return;size_t len=strnlen(buf,sizeof(buf));
 int fd=open("/tmp/boot1-native-wake/probe.log",O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC|O_NOFOLLOW,0600);
 if(fd>=0){(void)write(fd,buf,len);(void)write(fd,"\n",1);close(fd);}
}
static void observed(void *ctx,unsigned code,float angle) {
 pthread_mutex_lock(&lock);last_code=code;last_angle=angle;seen++;wake_fn fn=original_wake;pthread_mutex_unlock(&lock);
 note("WAKE_CALLBACK origin=%s ctx=%p code=0x%x angle=%.2f",synthetic?"probe":"native",ctx,code,(double)angle);
 if(!synthetic && code==1 && access("/tmp/boot1-native-wake/auto.armed",F_OK)==0 && unlink("/tmp/boot1-native-wake/auto.armed")==0){auto_at=time(NULL)+10;auto_angle=angle;note("AUTO scheduled at=%ld angle=%.2f",(long)auto_at,(double)angle);}
 if(fn)fn(ctx,code,angle);
}
void *xaudio_register_callback(void *engine,wake_fn callback,void *ctx) {
 if(!real_register)real_register=(register_fn)dlsym(RTLD_NEXT,"xaudio_register_callback");
 if(!real_register)return NULL;
 pthread_mutex_lock(&lock);original_wake=callback;wake_context=ctx;pthread_mutex_unlock(&lock);
 note("REGISTER engine=%p callback=%p context=%p",engine,(void*)callback,ctx);
 return real_register(engine,observed,ctx);
}
static int exists(const char *path){return access(path,F_OK)==0;}
static void *worker(void *arg) {
 (void)arg;
 for(unsigned tick=0;tick<4800;tick++) {
  usleep(100000);
  if(auto_at && time(NULL)>=auto_at){auto_at=0;int fd=open("/tmp/boot1-native-wake/trigger",O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC|O_NOFOLLOW,0600);if(fd>=0){char text[64];int n=snprintf(text,sizeof(text),"1 %.2f 2\n",(double)auto_angle);(void)write(fd,text,(size_t)n);close(fd);}}
  if(!exists("/tmp/boot1-native-wake/trigger"))continue;
  char command[64]={0};
  int control=open("/tmp/boot1-native-wake/trigger",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
  if(control<0)continue;(void)read(control,command,sizeof(command)-1);close(control);
  if(unlink("/tmp/boot1-native-wake/trigger"))continue;
  pthread_mutex_lock(&lock);wake_fn fn=original_wake;void *ctx=wake_context;unsigned code=last_code,samples=seen;float angle=last_angle;pthread_mutex_unlock(&lock);
  unsigned mode=0;
  if(sscanf(command,"%u %f %u",&code,&angle,&mode)!=3 || mode>3 || code!=1 || !(angle>=0 && angle<=360)){note("TRIGGER invalid command");continue;}
  if(!fn||!ctx||attempts>=4||time(NULL)-begin>480||exists("/tmp/mipns/mute")||exists("/tmp/native_first_busy")) {note("TRIGGER refused samples=%u attempts=%u",samples,attempts);continue;}
  attempts++;asr_frames=0;record_until=time(NULL)+10;
  if(record_fd>=0)close(record_fd);
  record_fd=open("/tmp/boot1-native-wake/live-asr.pcm",O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC|O_NOFOLLOW,0600);
  note("TRIGGER begin attempt=%u code=0x%x angle=%.2f",attempts,code,(double)angle);
  replay_until=mode==3?time(NULL)+6:0;
  if(mode==3 && !replay) {
   int fd=open("/tmp/boot1-native-wake/replay.pcm",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);struct stat st;
   if(fd>=0 && fstat(fd,&st)==0 && S_ISREG(st.st_mode) && st.st_size>0 && st.st_size<=640000) {
    unsigned char *data=malloc((size_t)st.st_size);
    if(data && read(fd,data,(size_t)st.st_size)==st.st_size){replay_size=(size_t)st.st_size;replay_cursor=0;replay=data;note("REPLAY loaded %u bytes",(unsigned)replay_size);}else free(data);
   }
   if(fd>=0)close(fd);
   if(!replay){note("REPLAY unavailable");continue;}
  }
  if(mode>=2)nonwake_until=time(NULL)+3;
  synthetic=1;observed(ctx,code,angle);synthetic=0;note("TRIGGER returned mode=%u",mode);
  if(mode && original_ivw){usleep(300000);unsigned char empty[320]={0};original_ivw(1,empty,0,0,0);note("IVW completion emitted len=0");}
 }
 note("probe trigger window expired");return NULL;
}
__attribute__((constructor)) static void initialize(void) {
 char exe[256];ssize_t n=readlink("/proc/self/exe",exe,sizeof(exe)-1);
 if(n<0)return;exe[n]=0;if(strcmp(exe,"/usr/bin/mipns-xiaomi"))return;
 unsetenv("LD_PRELOAD");begin=time(NULL);
 pthread_t thread;if(pthread_create(&thread,NULL,worker,NULL)==0)pthread_detach(thread);
 note("START pid=%d",(int)getpid());
}
