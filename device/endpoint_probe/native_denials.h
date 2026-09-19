/* Exact compact tombstones, never a probabilistic filter or expiry policy.
 * Publish the denial bucket BEFORE removing the matching individual record.
 * Readers inspect the individual record first, then this bucket. */
#ifndef NATIVE_DENIALS_H
#define NATIVE_DENIALS_H
#define NR_DENIAL_DIR NW_ROUTE_DIR ".denied"
#define NR_DENIAL_BYTES (128u*1024u)
static inline int nr_denial_directory(void){
    struct stat st;if(mkdir(NR_DENIAL_DIR,0700) && errno!=EEXIST)return 0;
    return !lstat(NR_DENIAL_DIR,&st) && S_ISDIR(st.st_mode) && st.st_uid==geteuid() && !(st.st_mode&077);
}
/* 0 absent, 1 denied, -1 invalid/unreadable: do not grant a new capability. */
static inline int nr_denied(const char *id){
    if(!nr_name(id))return -1;
    char path[256];snprintf(path,sizeof(path),NR_DENIAL_DIR "/b_%c",id[0]);
    struct stat dir;
    if(lstat(NR_DENIAL_DIR,&dir))return errno==ENOENT?0:-1;
    if(!S_ISDIR(dir.st_mode) || dir.st_uid!=geteuid() || (dir.st_mode&077))return -1;
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);if(fd<0)return errno==ENOENT?0:-1;
    struct stat st;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || (st.st_mode&077) || st.st_size<5 || st.st_size>(off_t)NR_DENIAL_BYTES){close(fd);return -1;}
    FILE *f=fdopen(fd,"r");if(!f){close(fd);return -1;}
    char line[128];int found=0,valid=fgets(line,sizeof(line),f) && !strcmp(line,"NRD1\n");
    while(valid && fgets(line,sizeof(line),f)){
        size_t n=strlen(line);if(!n || line[n-1]!='\n'){valid=0;break;}line[n-1]=0;
        if(!nr_name(line) || line[0]!=id[0]){valid=0;break;}
        if(!strcmp(line,id))found=1;
    }
    if(ferror(f))valid=0;fclose(f);return valid?found:-1;
}
/* Called only for an explicitly retired, cancelled/failed generation.
 * Malformed, foreign, quiet and live-generation records are preserved. */
static inline int nr_compact_denial(const struct nw_state *s){
    if(s->phase!=NW_CANCELLED || !s->modified || !nr_name(s->dialog) ||
       (s->end_reason!=NW_END_REPLACED && s->end_reason!=3))return 0;
    char path[256],record[128],pending[128],failed[128];
    snprintf(path,sizeof(path),NW_ROUTE_DIR "/%s",s->dialog);
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0)return errno==ENOENT && nr_denied(s->dialog)==1;
    struct stat before;
    int valid=!fstat(fd,&before) && nr_read(fd,record,sizeof(record)) &&
        nr_record(pending,sizeof(pending),s,"pending") && nr_record(failed,sizeof(failed),s,"failed") &&
        (!strcmp(record,pending) || !strcmp(record,failed));close(fd);
    if(!valid || !nr_denial_directory())return 0;
    int lock=open(NR_DENIAL_DIR "/guard",O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);struct stat ls;
    if(lock<0)return 0;
    if(fstat(lock,&ls) || !S_ISREG(ls.st_mode) || ls.st_uid!=geteuid() || (ls.st_mode&077) || flock(lock,LOCK_EX)){close(lock);return 0;}
    int exists=nr_denied(s->dialog),ok=0;
    if(exists<0)goto done;
    if(!exists){
        char bucket[256],temp[280];snprintf(bucket,sizeof(bucket),NR_DENIAL_DIR "/b_%c",s->dialog[0]);
        snprintf(temp,sizeof(temp),"%s.%u.tmp",bucket,(unsigned)getpid());
        int out=open(temp,O_CREAT|O_EXCL|O_WRONLY|O_CLOEXEC|O_NOFOLLOW,0600);if(out<0)goto done;
        int input=open(bucket,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);size_t total=0;ok=1;
        if(input<0){ok=errno==ENOENT && write(out,"NRD1\n",5)==5;total=5;}
        else {
            char block[4096];ssize_t n;
            while((n=read(input,block,sizeof(block)))>0){total+=(size_t)n;if(total>NR_DENIAL_BYTES || write(out,block,n)!=n){ok=0;break;}}
            if(n<0)ok=0;close(input);
        }
        size_t n=strlen(s->dialog);
        if(total+n+1>NR_DENIAL_BYTES || !ok || write(out,s->dialog,n)!=(ssize_t)n || write(out,"\n",1)!=1)ok=0;
        if(close(out))ok=0;
        if(ok)ok=!rename(temp,bucket);
        if(!ok){unlink(temp);goto done;}
    }
    /* Recheck exact inode and pending/failed contents after publication. */
    fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);struct stat after;
    ok=fd>=0 && !fstat(fd,&after) && before.st_dev==after.st_dev && before.st_ino==after.st_ino &&
        nr_read(fd,record,sizeof(record)) && (!strcmp(record,pending) || !strcmp(record,failed));
    if(fd>=0)close(fd);
    if(ok)ok=!lstat(path,&after) && before.st_dev==after.st_dev && before.st_ino==after.st_ino && !unlink(path);
done:
    close(lock);return ok;
}
#endif
