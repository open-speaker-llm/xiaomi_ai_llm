/* Reclaim only a verified, abandoned generation. Route evidence is retained. */
#ifndef NATIVE_WAKE_RECOVERY_H
#define NATIVE_WAKE_RECOVERY_H
#include <stddef.h>
#include <errno.h>

/* Held for the complete watcher lifetime. Never unlink the lock inode. */
static inline int nw_watch_lock(void) {
    int fd=open(NW_DIR "/watch.lock",O_RDWR|O_CREAT|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);
    struct stat st;
    if(fd<0)return -1;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() ||
       (st.st_mode&077) || flock(fd,LOCK_EX|LOCK_NB)){close(fd);return -1;}
    return fd;
}
/* Missing is safe; malformed or foreign files are never deleted. */
static inline int nw_old_file(const char *path,void *out,size_t bytes,size_t total,struct stat *st) {
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0)return errno==ENOENT?0:-1;
    int ok=!fstat(fd,st) && S_ISREG(st->st_mode) && st->st_uid==geteuid() &&
        !(st->st_mode&077) && st->st_size==(off_t)total && pread(fd,out,bytes,0)==(ssize_t)bytes;
    close(fd);return ok?1:-1;
}
static inline int nw_unlink_same(const char *path,const struct stat *before) {
    struct stat after;
    return !lstat(path,&after) && before->st_dev==after.st_dev && before->st_ino==after.st_ino && !unlink(path);
}
/* Caller owns watch.lock. 0 = clear; 3 = old helper still exiting; 2 = refuse.
 * A live owner is preserved even if its lease expired or PID was reused. */
static inline int nw_recover_abandoned(void) {
    struct nw_state old;struct stat state_stat;
    int exists=nw_old_file(NW_FILE,&old,sizeof(old),sizeof(old),&state_stat);
    if(!exists)return 0;
    if(exists<0 || old.magic!=NW_MAGIC || old.owner<=1 || old.mode>3 ||
       old.phase>NW_CANCELLED || !memchr(old.dialog,0,sizeof(old.dialog)) || alive(old.owner))return 2;
    char path[256],decision_path[272];struct stat stream_stat,decision_stat;
    int stream_exists=0,decision_exists=0;
    if(old.mode){
        if(!old.nonce || old.observer==1 || (!old.observer && old.phase!=NW_CANCELLED))return 2;
        if(alive(old.observer))return 3;
        nw_stream_path(path,sizeof(path),&old);snprintf(decision_path,sizeof(decision_path),"%s.decision",path);
        struct neural_stream header;struct neural_decision decision;
        stream_exists=nw_old_file(path,&header,offsetof(struct neural_stream,pcm),sizeof(header),&stream_stat);
        decision_exists=nw_old_file(decision_path,&decision,sizeof(decision),sizeof(decision),&decision_stat);
        /* Before the fork handshake no helper may create either file. */
        if(!old.observer && (stream_exists || decision_exists))return 2;
        if(stream_exists<0 || decision_exists<0 ||
           (stream_exists && (!ns_identity(&header,old.nonce,old.owner) || header.observer!=old.observer)) ||
           (decision_exists && !nd_identity(&decision,old.nonce,old.owner,old.observer)))return 2;
        if(stream_exists && !nw_unlink_same(path,&stream_stat))return 2;
        if(decision_exists && !nw_unlink_same(decision_path,&decision_stat))return 2;
    }
    if(!nw_unlink_same(NW_FILE,&state_stat))return 2;
    printf("FIRST_RECOVERED owner=%u nonce=%u route_evidence=retained\n",old.owner,old.nonce);
    return 0;
}
#endif
