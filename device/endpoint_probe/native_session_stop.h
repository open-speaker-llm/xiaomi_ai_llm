/* Private local stop request. Never signal a PID read from a stale file. */
#ifndef NATIVE_SESSION_STOP_H
#define NATIVE_SESSION_STOP_H
#include <sys/socket.h>
#include <sys/un.h>
static int nss_socket(void){
    int fd=socket(AF_UNIX,SOCK_DGRAM,0);if(fd<0)return -1;
    if(fcntl(fd,F_SETFD,FD_CLOEXEC) || fcntl(fd,F_SETFL,O_NONBLOCK)){close(fd);return -1;}
    return fd;
}
static int nss_address(struct sockaddr_un *address,const char *path){
    if(strlen(path)>=sizeof(address->sun_path))return 0;
    memset(address,0,sizeof(*address));address->sun_family=AF_UNIX;
    strcpy(address->sun_path,path);return 1;
}
static int nss_private_socket(const struct stat *st){
    return S_ISSOCK(st->st_mode) && st->st_uid==geteuid() && !(st->st_mode&077);
}
static int nss_listen(const char *path){
    struct stat st;struct sockaddr_un address;
    if(!nss_address(&address,path))return -1;
    if(!lstat(path,&st)){if(!nss_private_socket(&st) || unlink(path))return -1;}
    else if(errno!=ENOENT)return -1;
    int fd=nss_socket();if(fd<0)return -1;
    if(bind(fd,(const struct sockaddr *)&address,sizeof(address))){close(fd);return -1;}
    return fd;
}
static int nss_requested(int fd){
    if(fd<0)return 0;
    for(unsigned i=0;i<8;i++){
        char message[16];ssize_t n=recv(fd,message,sizeof(message),0);
        if(n<0)return 0;
        if(n==8 && !memcmp(message,"STOP_V1\n",8))return 1;
    }
    return 0;
}
static int nss_stop(const char *guard,const char *path){
    int lock=open(guard,O_RDWR|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);struct stat st;
    if(lock<0)return errno==ENOENT?0:2;
    if(fstat(lock,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || (st.st_mode&077)){close(lock);return 2;}
    struct sockaddr_un address;if(!nss_address(&address,path)){close(lock);return 2;}
    int fd=nss_socket();if(fd<0){close(lock);return 2;}
    uint32_t until=now_ms()+5000;int sent=0,rc=1;
    while((int32_t)(until-now_ms())>0){
        if(!flock(lock,LOCK_EX|LOCK_NB)){rc=0;break;}
        if(errno!=EWOULDBLOCK && errno!=EAGAIN){rc=2;break;}
        if(!sent){
            if(!lstat(path,&st)){
                if(!nss_private_socket(&st)){rc=2;break;}
                sent=sendto(fd,"STOP_V1\n",8,0,(const struct sockaddr *)&address,sizeof(address))==8;
            }else if(errno!=ENOENT){rc=2;break;}
        }
        usleep(20000);
    }
    close(fd);close(lock);
    if(!rc)puts(sent?"FIRST_SESSION_STOPPED":"FIRST_SESSION_IDLE");
    return rc;
}
#endif
