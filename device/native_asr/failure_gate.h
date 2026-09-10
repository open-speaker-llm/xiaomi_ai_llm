/* Synchronous failure-Speak gate. No audio, signals or user text are written.
 * The shell client publishes its PID/regex only while it can consume handoffs.
 * Keep the log-polling guard as a fallback when this gate cannot safely act. */
#ifndef NATIVE_FAILURE_GATE_H
#define NATIVE_FAILURE_GATE_H
#include <regex.h>
#ifndef FAILURE_ARMED_FILE
#define FAILURE_ARMED_FILE "/tmp/native_first_aivs_guard_armed"
#endif
#define FAILURE_POLICY_FILE CONTROL_DIR "/failure_policy"
#define FAILURE_DIALOG_FILE CONTROL_DIR "/failure_dialog"
static pthread_mutex_t failure_lock=PTHREAD_MUTEX_INITIALIZER;
static char failure_observed[80], failure_blocked[64][80];
static uint32_t failure_owner, failure_deadline;
static unsigned failure_cursor;

static int failure_id_valid(const char *id) {
    size_t n=strlen(id);
    return n && n<80 && strspn(id,"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")==n;
}
static uint32_t failure_policy(char *pattern,size_t capacity) {
    char data[2048]; struct stat st; uint32_t owner=0;
    int fd=open(FAILURE_POLICY_FILE,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if (fd<0) return 0;
    int valid=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_uid==geteuid() &&
        !(st.st_mode&022) && st.st_size>0 && st.st_size<(off_t)sizeof(data);
    ssize_t n=valid ? read(fd,data,(size_t)st.st_size) : -1;
    valid=valid && n==st.st_size;
    close(fd);
    if (!valid) return 0;
    data[n]=0; char *end;
    unsigned long pid=strtoul(data,&end,10);
    if (pid>1 && pid<=INT32_MAX && *end=='\n') owner=(uint32_t)pid;
    if (!owner || !alive(owner) || access(NATIVE_BUSY_FILE,F_OK)==0) return 0;
    if (lstat(FAILURE_ARMED_FILE,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid()) return 0;
    time_t age=time(NULL)-st.st_mtime;
    if (age<0 || age>20) return 0;
    char *regex=end+1; size_t len=strlen(regex);
    if (len && regex[len-1]=='\n') regex[--len]=0;
    if (!len || len>=capacity || strchr(regex,'\n')) return 0;
    memcpy(pattern,regex,len+1);
    return owner;
}
static void failure_observe_final(const char *id) {
    if (!failure_id_valid(id)) return;
    char pattern[2048]; uint32_t owner=failure_policy(pattern,sizeof(pattern));
    pthread_mutex_lock(&failure_lock);
    snprintf(failure_observed,sizeof(failure_observed),"%s",owner?id:"");
    failure_owner=owner; failure_deadline=now_ms()+15000;
    pthread_mutex_unlock(&failure_lock);
}
static int failure_publish(uint32_t owner,const char *id) {
    char path[]=CONTROL_DIR "/failure_dialog.XXXXXX", data[112];
    int n=snprintf(data,sizeof(data),"%u %s\n",owner,id);
    int fd=mkstemp(path);
    if (fd<0) return 0;
    int ok=!fchmod(fd,0600) && write(fd,data,(size_t)n)==n;
    if (close(fd)) ok=0;
    if (ok && rename(path,FAILURE_DIALOG_FILE)) ok=0;
    if (!ok) unlink(path);
    return ok;
}
static int failure_block_speak(const char *id,const char *text) {
    if (!failure_id_valid(id)) return 0;
    pthread_mutex_lock(&failure_lock);
    /* The SDK parses instructions twice. A blocked dialog stays blocked even
     * after the client sets busy/removes the arm marker to start the LLM. */
    for (unsigned i=0;i<64;i++) if (!strcmp(id,failure_blocked[i])) {
        pthread_mutex_unlock(&failure_lock); return 1;
    }
    char pattern[2048]; uint32_t owner=failure_policy(pattern,sizeof(pattern));
    int block=0;
    if (owner && owner==failure_owner && !strcmp(id,failure_observed) &&
        (int32_t)(failure_deadline-now_ms())>0 && *text && strlen(text)<=8192) {
        regex_t regex;
        if (!regcomp(&regex,pattern,REG_EXTENDED|REG_NOSUB)) {
            block=!regexec(&regex,text,0,NULL,0);
            regfree(&regex);
        }
        /* Fail open if the client cannot receive the exact dialog handoff. */
        if (block) block=failure_publish(owner,id);
        if (block) snprintf(failure_blocked[failure_cursor++%64],80,"%s",id);
    }
    pthread_mutex_unlock(&failure_lock);
    if (block) note("failure Speak blocked before dispatch dialog=%s",id);
    return block;
}
#endif
