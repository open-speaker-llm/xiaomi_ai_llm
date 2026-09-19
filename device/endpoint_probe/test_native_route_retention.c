/* Private journal-only stress test; no microphone, native daemons or cloud. */
#include "native_wake_state.h"
#include "native_route.h"
#include <assert.h>
static void put(const char *name,const char *record){
    char path[256];snprintf(path,sizeof(path),NW_ROUTE_DIR "/%s",name);
    int fd=open(path,O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0);
    size_t n=strlen(record);assert(write(fd,record,n)==(ssize_t)n);close(fd);
}
static unsigned count(void){
    DIR *dir=opendir(NW_ROUTE_DIR);assert(dir);unsigned n=0;struct dirent *e;
    while((e=readdir(dir)))if(strcmp(e->d_name,".") && strcmp(e->d_name,".."))n++;
    closedir(dir);return n;
}
int main(void){
    assert(!mkdir(NW_DIR,0700));assert(nr_directory());
    struct nw_state s={.magic=NW_MAGIC,.owner=getpid(),.observer=getpid(),.nonce=1,
        .deadline=now_ms()+90000,.mode=3,.phase=NW_BOUND,.prepared=1,.accepted=1,
        .modified=1,.ended=1,.end_reason=1,.final_seen=1,.finished=1,
        .producer=getpid(),.consumer=getpid(),.expected_producer=getpid(),.expected_consumer=getpid()};
    memset(s.tag,71,sizeof(s.tag));
    strcpy(s.dialog,"pending");assert(nr_begin(&s));
    strcpy(s.dialog,"failed");assert(nr_begin(&s));assert(nr_finish(&s,0));
    put("broken","NW1 2 3 a quiet\n");put("extra","NW1 2 3 abababababababababababababababab quiet\nextra\n");
    put("orphan.123.tmp","NW1 2 3 abababababababababababababababab quiet\n");
    put("embedded-nul","NW1 2 3 abababababababababababababababab quiet\n");
    int binary=open(NW_ROUTE_DIR "/embedded-nul",O_WRONLY|O_APPEND);assert(binary>=0);
    assert(write(binary,"\0junk",5)==5);close(binary);
    assert(!symlink("missing",NW_ROUTE_DIR "/symlink"));
    unsigned removed=0;
    for(unsigned i=0;i<600;i++){
        int n=nr_prune_completed(32);assert(n>=0);removed+=(unsigned)n;
        s.nonce++;snprintf(s.dialog,sizeof(s.dialog),"success-%04u",i);
        assert(nr_begin(&s) && nr_finish(&s,1));assert(count()<=40);
    }
    assert(removed==567 && count()==40);
    int n=nr_prune_completed(0);assert(n==33 && count()==7);
    char record[128];int fd=open(NW_ROUTE_DIR "/pending",O_RDONLY);
    assert(fd>=0 && nr_read(fd,record,sizeof(record)));close(fd);assert(strstr(record," pending\n"));
    fd=open(NW_ROUTE_DIR "/failed",O_RDONLY);
    assert(fd>=0 && nr_read(fd,record,sizeof(record)));close(fd);assert(strstr(record," failed\n"));
    for(unsigned i=7;i<NW_ROUTE_MAX-1;i++){
        char name[80];snprintf(name,sizeof(name),"protected-%04u",i);put(name,"unknown\n");
    }
    /* At capacity, even the last quiet record is reclaimable; denial stays. */
    strcpy(s.dialog,"last-quiet");assert(nr_begin(&s) && nr_finish(&s,1));
    assert(count()==NW_ROUTE_MAX && nr_prune_completed(32)==1);
    put("protected-last","unknown\n");
    assert(count()==NW_ROUTE_MAX && nr_prune_completed(0)==0);
    strcpy(s.dialog,"capacity-refused");assert(!nr_begin(&s));
    DIR *dir=opendir(NW_ROUTE_DIR);assert(dir);struct dirent *e;
    while((e=readdir(dir)))if(strcmp(e->d_name,".") && strcmp(e->d_name,"..")){
        char path[256];snprintf(path,sizeof(path),NW_ROUTE_DIR "/%s",e->d_name);assert(!unlink(path));
    }
    closedir(dir);assert(!rmdir(NW_ROUTE_DIR));assert(!rmdir(NW_DIR));
    puts("PASS route retention: 600 successes bounded; denial and malformed evidence retained; protected capacity refuses new capture");
    return 0;
}
