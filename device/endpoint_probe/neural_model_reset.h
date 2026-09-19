/* Fixed sherpa-onnx 1.10.36 / Silero v5 adapter. Include the pinned C API first.
 * A fresh detector uses the original framing. A reused detector must call
 * nm_begin(), then feed complete 160-sample frames through nm_frame().
 * Only read/publish detection AFTER nm_frame succeeds. The temporary reseed
 * inference is never a candidate and never becomes uploaded PCM. */
#ifndef NEURAL_MODEL_RESET_H
#define NEURAL_MODEL_RESET_H
#include "neural_reset.h"
struct neural_model_reset {
    uint32_t pending;
    int reseed;
};
struct neural_reset_api {
    __typeof__(&SherpaOnnxVoiceActivityDetectorReset) reset;
    __typeof__(&SherpaOnnxVoiceActivityDetectorAcceptWaveform) accept;
    __typeof__(&SherpaOnnxVoiceActivityDetectorDetected) detected;
    __typeof__(&SherpaOnnxVoiceActivityDetectorEmpty) empty;
};
static inline void nm_begin(struct neural_model_reset *m){m->reseed=1;}
static inline int nm_frame(struct neural_model_reset *m,struct neural_reset_api api,
                          SherpaOnnxVoiceActivityDetector *vad,const float frame[160]){
    if(m->pending>=576)return 0;
    if(m->reseed){
        float scratch[1088];uint32_t n=nz_reseed(scratch,m->pending,frame);
        if(!n)return 0;
        api.reset(vad);api.accept(vad,scratch,(int32_t)n);
        m->pending=nz_pending(m->pending,n);api.reset(vad);
        if(m->pending!=64 || api.detected(vad) || !api.empty(vad))return 0;
        api.accept(vad,frame+64,96);m->pending=nz_pending(m->pending,96);
        m->reseed=0;
    }else{
        api.accept(vad,frame,160);m->pending=nz_pending(m->pending,160);
    }
    return 1;
}
#endif
