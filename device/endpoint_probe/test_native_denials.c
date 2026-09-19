/* 1200 cancelled dialogs compacted without making old finals eligible. */
#include "native_wake_state.h"
#include "native_route.h"
#undef NDEBUG
#include <assert.h>
int main(void){
 assert(!mkdir(NW_DIR,0700));assert(nr_directory());
 struct nw_state s={.magic=NW_MAGIC,.owner=getpid(),.observer=getpid(),.nonce=1,.phase=NW_CANCELLED,.modified=1,.end_reason=NW_END_REPLACED};
 memset(s.tag,71,sizeof(s.tag));
 for(unsigned i=0;i<1200;i++){
  snprintf(s.dialog,sizeof(s.dialog),"%xcancel-%04u",i%16,i);s.nonce++;
  assert(nr_denied(s.dialog)==0 && nr_begin(&s));
  struct nw_state wrong=s;wrong.nonce++;assert(!nr_compact_denial(&wrong));
  assert(nr_compact_denial(&s) && nr_compact_denial(&s));
  assert(nr_denied(s.dialog)==1 && !nr_begin(&s));
 }
 for(unsigned i=0;i<1200;i++){
  char id[80];snprintf(id,sizeof(id),"%xcancel-%04u",i%16,i);assert(nr_denied(id)==1);
 }
 assert(nr_denied("0cancel-0000-extra")==0 && nr_has_capacity());
 strcpy(s.dialog,"active");assert(nr_begin(&s));s.phase=NW_BOUND;assert(!nr_compact_denial(&s));
 s.phase=NW_CANCELLED;assert(nr_compact_denial(&s));
 /* Existing corrupt evidence is preserved, not overwritten or ignored. */
 int fd=open(NR_DENIAL_DIR "/b_z",O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0);assert(write(fd,"NRD1\nzbad",9)==9);close(fd);
 assert(nr_denied("znew")==-1);strcpy(s.dialog,"znew");assert(!nr_begin(&s));
 size_t bytes=0;unsigned buckets=0;
 DIR *dir=opendir(NR_DENIAL_DIR);assert(dir);struct dirent *e;
 while((e=readdir(dir)))if(strcmp(e->d_name,".") && strcmp(e->d_name,"..")){
  char path[256];snprintf(path,sizeof(path),NR_DENIAL_DIR "/%s",e->d_name);struct stat st;assert(!lstat(path,&st));
  bytes+=(size_t)st.st_size;if(!strncmp(e->d_name,"b_",2))buckets++;assert(!unlink(path));
 }
 closedir(dir);assert(buckets==17 && bytes<20000);
 assert(!rmdir(NR_DENIAL_DIR));assert(!rmdir(NW_ROUTE_DIR));assert(!rmdir(NW_DIR));
 printf("DENIAL_STRESS dialogs=1201 bytes=%zu buckets=%u old_ids=denied live_files=0\n",bytes,buckets);return 0;
}
