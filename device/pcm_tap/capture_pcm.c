/* Read newly published processed PCM. Does not touch ALSA or native state. */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#include "pcm_ring.h"
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
static volatile sig_atomic_t active=1;
static void stop(int sig){(void)sig;active=0;}
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static void put16(FILE*f,uint32_t n){fputc(n&255,f);fputc((n>>8)&255,f);}
static void put32(FILE*f,uint32_t n){put16(f,n);put16(f,n>>16);}
static int write_wav(const char *path,int16_t *buf,uint32_t n){
    int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW,0600);if(fd<0)return 1;
    FILE*f=fdopen(fd,"wb");if(!f){close(fd);return 1;}
    fwrite("RIFF",1,4,f);put32(f,36+n*2);fwrite("WAVEfmt ",1,8,f);
    put32(f,16);put16(f,1);put16(f,1);put32(f,PCM_RATE);put32(f,PCM_RATE*2);
    put16(f,2);put16(f,16);fwrite("data",1,4,f);put32(f,n*2);
    int err=fwrite(buf,2,n,f)!=n;err|=fclose(f)!=0;return err;
}
int main(int argc,char**argv){
    int check=argc>=2 && !strcmp(argv[1],"--check");
    double seconds=0.1;
    const char *path=PCM_RING_PATH;
    if(check){
        if(argc>3)return 2;
        if(argc==3)path=argv[2];
    }else{
        if(argc<3 || argc>4){fprintf(stderr,"usage: capture_pcm output.wav seconds [ring_path] | --check [ring_path]\n");return 2;}
        char *end;seconds=strtod(argv[2],&end);
        if(*end || !isfinite(seconds) || seconds<1 || seconds>30)return 2;
        if(argc==4)path=argv[3];
    }
    if(access("/tmp/mipns/mute",F_OK)==0)return 1;
    int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0){perror("ring");return 1;}
    struct stat st;if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size!=(off_t)sizeof(struct pcm_ring)){close(fd);return 1;}
    struct pcm_ring *r=mmap(NULL,sizeof(*r),PROT_READ,MAP_SHARED,fd,0);close(fd);
    if(r==MAP_FAILED)return 1;
    if(__atomic_load_n(&r->magic,__ATOMIC_ACQUIRE)!=PCM_MAGIC || r->version!=1 ||
       r->rate!=PCM_RATE || r->block_samples!=PCM_SAMPLES || r->slots!=PCM_SLOTS){munmap(r,sizeof(*r));return 1;}
    uint32_t producer=r->producer_pid,read_frame=__atomic_load_n(&r->published,__ATOMIC_ACQUIRE);
    uint32_t target=(uint32_t)(seconds*100)*PCM_SAMPLES,used=0;
    int16_t *samples=calloc(target,sizeof(int16_t));if(!samples){munmap(r,sizeof(*r));return 1;}
    signal(SIGTERM,stop);signal(SIGINT,stop);
    double start=now(),last=start;int failure=0;
    fprintf(stderr,"PCM_CAPTURE start producer=%u seconds=%.2f\n",producer,seconds);
    while(active && used<target && now()-start<seconds+3){
        if(access("/tmp/mipns/mute",F_OK)==0){failure=1;break;}
        uint32_t next=__atomic_load_n(&r->published,__ATOMIC_ACQUIRE);
        if(r->producer_pid!=producer || next-read_frame>PCM_SLOTS){failure=1;break;}
        if(next==read_frame){if(now()-last>2){failure=1;break;}struct timespec t={0,5000000};nanosleep(&t,NULL);continue;}
        struct pcm_block *b=&r->blocks[read_frame%PCM_SLOTS];
        uint32_t expected=read_frame*2+2;
        if(__atomic_load_n(&b->sequence,__ATOMIC_ACQUIRE)!=expected){failure=1;break;}
        memcpy(samples+used,b->samples,sizeof(b->samples));
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if(__atomic_load_n(&b->sequence,__ATOMIC_ACQUIRE)!=expected){failure=1;break;}
        read_frame++;used+=PCM_SAMPLES;last=now();
    }
    if(!active || used!=target)failure=1;
    if(!failure && !check)failure=write_wav(argv[1],samples,used);
    fprintf(stderr,"PCM_CAPTURE done samples=%u seconds=%.2f status=%s\n",used,now()-start,failure?"error":"ok");
    free(samples);munmap(r,sizeof(*r));return failure;
}
