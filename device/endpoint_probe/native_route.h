/* Per-dialog routing evidence survives watcher/owner exit. No speech content. */
#ifndef NATIVE_ROUTE_H
#define NATIVE_ROUTE_H
#include <dirent.h>
#include <errno.h>
#include <stdlib.h>
#define NW_ROUTE_DIR NW_DIR "/routes"
#define NW_ROUTE_MAX 256u
static inline int nr_name(const char *s) {
    size_t n=strlen(s);if(!n || n>=80)return 0;
    for(size_t i=0;i<n;i++)if(!((s[i]>='a' && s[i]<='z') ||
       (s[i]>='A' && s[i]<='Z') || (s[i]>='0' && s[i]<='9') || s[i]=='-' || s[i]=='_'))return 0;
    return 1;
}
static inline int nr_directory(void) {
    struct stat st;
    if(mkdir(NW_ROUTE_DIR,0700) && errno!=EEXIST)return 0;
    return !lstat(NW_ROUTE_DIR,&st) && S_ISDIR(st.st_mode) && st.st_uid==geteuid() && !(st.st_mode&077);
}
static inline int nr_record(char *out,size_t size,const struct nw_state *s,const char *status) {
    char tag[NW_TAG_BYTES*2+1];for(unsigned i=0;i<NW_TAG_BYTES;i++)snprintf(tag+2*i,3,"%02x",s->tag[i]);
    int n=snprintf(out,size,"NW1 %u %u %s %s\n",s->owner,s->nonce,tag,status);
    return n>0 && (size_t)n<size?n:0;
}
static inline int nr_read(int fd,char *record,size_t size) {
    struct stat st;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() ||
       (st.st_mode&077) || st.st_size<1 || st.st_size>=(off_t)size)return 0;
    ssize_t n=pread(fd,record,size-1,0);
    if(n!=st.st_size || memchr(record,0,(size_t)n))return 0;
    record[n]=0;return 1;
}
#include "native_denials.h"
/* Quiet is terminal permission, so forgetting it cannot turn a denial into
 * permission. Pending/failed/unknown records must never be aged out. */
static inline int nr_quiet_record(const char *record){
    unsigned owner,nonce;char tag[33],extra,canonical[128];
    if(sscanf(record,"NW1 %u %u %32[0-9a-f] quiet %c",&owner,&nonce,tag,&extra)!=3 ||
       owner<=1 || !nonce || strlen(tag)!=32)return 0;
    int n=snprintf(canonical,sizeof(canonical),"NW1 %u %u %s quiet\n",owner,nonce,tag);
    return n>0 && n<(int)sizeof(canonical) && !strcmp(record,canonical);
}
struct nr_candidate {char name[80];struct stat st;};
static int nr_older(const void *left,const void *right){
    const struct nr_candidate *a=left,*b=right;
    if(a->st.st_mtime!=b->st.st_mtime)return a->st.st_mtime<b->st.st_mtime?-1:1;
    return strcmp(a->name,b->name);
}
/* Run under the controller/watch lock, outside native audio/JSON callbacks.
 * Keep recent successes for diagnostics; protected entries stay. */
static inline int nr_prune_completed(unsigned keep){
    struct stat directory_stat;
    if(lstat(NW_ROUTE_DIR,&directory_stat))return errno==ENOENT?0:-1;
    if(!nr_directory())return -1;
    DIR *directory=opendir(NW_ROUTE_DIR);if(!directory)return -1;
    struct nr_candidate *items=calloc(NW_ROUTE_MAX,sizeof(*items));
    if(!items){closedir(directory);return -1;}
    unsigned count=0,total=0;struct dirent *entry;
    while((entry=readdir(directory))){
        if(!strcmp(entry->d_name,".") || !strcmp(entry->d_name,".."))continue;
        total++;
        if(!nr_name(entry->d_name) || count>=NW_ROUTE_MAX)continue;
        char path[256],record[128];snprintf(path,sizeof(path),NW_ROUTE_DIR "/%s",entry->d_name);
        int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);if(fd<0)continue;
        struct stat st;
        int quiet=nr_read(fd,record,sizeof(record)) && nr_quiet_record(record) && !fstat(fd,&st);
        close(fd);if(!quiet)continue;
        snprintf(items[count].name,sizeof(items[count].name),"%s",entry->d_name);
        items[count++].st=st;
    }
    closedir(directory);qsort(items,count,sizeof(*items),nr_older);
    unsigned protected=total-count;
    unsigned room=protected<NW_ROUTE_MAX?NW_ROUTE_MAX-protected-1:0;
    if(keep>room)keep=room;
    int removed=0;
    for(unsigned i=0;count>keep && i<count-keep;i++){
        char path[256],record[128];struct stat st;
        snprintf(path,sizeof(path),NW_ROUTE_DIR "/%s",items[i].name);
        int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);if(fd<0)continue;
        int same=!fstat(fd,&st) && st.st_dev==items[i].st.st_dev && st.st_ino==items[i].st.st_ino &&
            nr_read(fd,record,sizeof(record)) && nr_quiet_record(record);
        close(fd);
        if(same && !lstat(path,&st) && st.st_dev==items[i].st.st_dev && st.st_ino==items[i].st.st_ino && !unlink(path))removed++;
    }
    free(items);return removed;
}
static inline int nr_complete(const struct nw_state *s,int helper_ok) {
    return helper_ok && nw_endpoint_identity(s) && s->modified && s->ended &&
        s->end_reason==1 && !s->failed && s->final_seen && s->finished;
}
static inline int nr_has_capacity(void){
    struct stat st;if(lstat(NW_ROUTE_DIR,&st))return errno==ENOENT;
    if(!nr_directory())return 0;
    DIR *directory=opendir(NW_ROUTE_DIR);if(!directory)return 0;
    unsigned count=0;struct dirent *entry;
    while((entry=readdir(directory)))if(strcmp(entry->d_name,".") && strcmp(entry->d_name,"..")){
        if(++count>=NW_ROUTE_MAX)break;
    }
    closedir(directory);return count<NW_ROUTE_MAX;
}
/* Called while holding this generation's nw state lock, before changing JSON.
 * Never evict an unresolved record to make space for a new experiment. */
static inline int nr_begin(const struct nw_state *s) {
    if(!nr_name(s->dialog) || !nr_directory() || nr_denied(s->dialog)!=0)return 0;
    if(!nr_has_capacity())return 0;
    char path[256],record[128];snprintf(path,sizeof(path),NW_ROUTE_DIR "/%s",s->dialog);
    int n=nr_record(record,sizeof(record),s,"pending");if(!n)return 0;
    int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0)return 0;
    int ok=write(fd,record,(size_t)n)==n;close(fd);return ok;
}
/* Only a pending record owned by this exact generation can be completed.
 * Atomic rename makes interrupted writes remain pending, never partially quiet. */
static inline int nr_finish(const struct nw_state *s,int quiet) {
    if(quiet && !nr_complete(s,1))return 0;
    if(!nr_name(s->dialog) || !nr_directory())return 0;
    char path[256],temp[280],expected[128],record[128];
    snprintf(path,sizeof(path),NW_ROUTE_DIR "/%s",s->dialog);
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return 0;
    int ok=nr_read(fd,record,sizeof(record));close(fd);
    if(!nr_record(expected,sizeof(expected),s,"pending") || !ok || strcmp(record,expected))return 0;
    snprintf(temp,sizeof(temp),"%s.%u.tmp",path,(unsigned)getpid());
    int n=nr_record(record,sizeof(record),s,quiet?"quiet":"failed");if(!n)return 0;
    fd=open(temp,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0)return 0;
    ok=write(fd,record,(size_t)n)==n;close(fd);
    if(ok)ok=!rename(temp,path);
    if(!ok)unlink(temp);
    return ok;
}
#endif
