/* Device integration fixture. Publishes synthetic frames into its own /tmp
 * ring, never the live ring. Runs the real shadow_capture consumer and VAD.
 */
#define _POSIX_C_SOURCE 200809L
#include "../pcm_tap/pcm_ring.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
int main(int argc,char **argv) {
    if(argc!=4)return 2;
    int stalled=!strcmp(argv[3],"stall");
    if(!stalled && strcmp(argv[3],"complete"))return 2;
    FILE *pcm=fopen(argv[2],"rb");assert(pcm);
    char dir[]="/tmp/shadow_stream_test.XXXXXX";assert(mkdtemp(dir));
    char ring[128],wav[128];
    assert(snprintf(ring,sizeof(ring),"%s/ring",dir)>0);
    assert(snprintf(wav,sizeof(wav),"%s/audio.wav",dir)>0);
    int fd=open(ring,O_RDWR|O_CREAT|O_EXCL,0600);assert(fd>=0);
    assert(!ftruncate(fd,sizeof(struct pcm_ring)));
    struct pcm_ring *r=mmap(NULL,sizeof(*r),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    assert(r!=MAP_FAILED);close(fd);
    r->version=1;r->rate=PCM_RATE;r->block_samples=PCM_SAMPLES;r->slots=PCM_SLOTS;
    r->producer_pid=(uint32_t)getpid();__atomic_store_n(&r->magic,PCM_MAGIC,__ATOMIC_RELEASE);
    int output[2];assert(!pipe(output));
    pid_t child=fork();assert(child>=0);
    if(!child) {
        close(output[0]);assert(dup2(output[1],STDERR_FILENO)>=0);close(output[1]);
        assert(!setenv("PCM_CAPTURE_TIMELINE","1",1));
        execl(argv[1],argv[1],wav,"10",ring,(char *)NULL);_exit(127);
    }
    close(output[1]);FILE *trace=fdopen(output[0],"r");assert(trace);
    char line[512];int ready=0;
    while(fgets(line,sizeof(line),trace)) {
        fputs(line,stdout);
        if(!strncmp(line,"PCM_CLOCK ",10)){ready=1;break;}
    }
    assert(ready);
    for(unsigned i=0;i<(stalled?100u:1000u);i++) {
        int16_t frame[PCM_SAMPLES]={0};
        size_t n=fread(frame,sizeof(*frame),PCM_SAMPLES,pcm);
        assert(n==0 || n==PCM_SAMPLES);assert(!ferror(pcm));
        struct pcm_block *b=&r->blocks[i%PCM_SLOTS];
        __atomic_store_n(&b->sequence,i*2+1,__ATOMIC_SEQ_CST);
        memcpy(b->samples,frame,sizeof(frame));
        __atomic_store_n(&b->sequence,i*2+2,__ATOMIC_RELEASE);
        __atomic_store_n(&r->published,i+1,__ATOMIC_RELEASE);
        struct timespec delay={0,2000000};nanosleep(&delay,NULL);
    }
    fclose(pcm);
    unsigned candidates=0,resumes=0;int valid=0,invalid=0;
    while(fgets(line,sizeof(line),trace)) {
        fputs(line,stdout);
        if(!strncmp(line,"SHADOW_CANDIDATE ",17))candidates++;
        if(!strncmp(line,"SHADOW_RESUME ",14))resumes++;
        if(strstr(line,"SHADOW_DONE ")) {
            valid=strstr(line,"status=ok")!=NULL;
            invalid=strstr(line,"status=invalid")!=NULL;
        }
    }
    fclose(trace);int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status));
    if(stalled) {
        assert(WEXITSTATUS(status)!=0 && invalid && !valid && access(wav,F_OK));
    } else {
        struct stat st;assert(!WEXITSTATUS(status) && valid && !invalid);
        assert(candidates==3 && resumes==0);assert(!stat(wav,&st) && st.st_size==320044);
        assert(!unlink(wav));
    }
    assert(!munmap(r,sizeof(*r)));assert(!unlink(ring));assert(!rmdir(dir));
    puts(stalled?"PASS: stalled private producer invalidates shadow and leaves no WAV":
         "PASS: accelerated private stream uses sample time; full WAV and three terminal suggestions");
    return 0;
}
