/* micnorm —— 追问录音电平归一化（保住分辨率）。
 * 背景：Capture 原生 S32/48k，安静语音在 S32 里信号很小但保有 ~23bit 分辨率；
 * 若直接 arecord -f S16 采集，ALSA 取高 16 位会把安静语音砍到 ~8bit，云端 ASR 识别不了。
 * 本工具读 S32_LE/mono WAV，在 float 域峰值归一化后输出 S16_LE/mono WAV（同采样率），
 * 既抬电平又保住分辨率。
 *
 * 进一步用分块 AGC（压缩器）：句尾说轻的部分给更大增益、句首响的少给，把整句电平拉平，
 * 改善"后半句录不全"。静音/间隙块不抬（防放大噪声），块间增益平滑防抽水。
 *
 * 用法: micnorm in_s32.wav out_s16.wav [target_peak=18000] [min_peak_s32=3000000] [max_boost=6]
 * 退出码: 0 成功；124 信号过弱(无有效语音)；1 错误。
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

static int cmp_d(const void *a, const void *b) {
    double x = *(const double*)a, y = *(const double*)b;
    return (x < y) ? -1 : (x > y) ? 1 : 0;
}

static long find_chunk(const unsigned char *b, long sz, const char *id, long *len) {
    long i = 12;
    while (i + 8 <= sz) {
        long clen = b[i+4] | (b[i+5]<<8) | (b[i+6]<<16) | ((long)b[i+7]<<24);
        if (memcmp(b+i, id, 4) == 0) { *len = clen; return i + 8; }
        i += 8 + clen + (clen & 1);
    }
    return -1;
}

static void put32(FILE *f, uint32_t v){fputc(v&255,f);fputc((v>>8)&255,f);fputc((v>>16)&255,f);fputc((v>>24)&255,f);}
static void put16(FILE *f, uint16_t v){fputc(v&255,f);fputc((v>>8)&255,f);}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s in_s32.wav out_s16.wav [target_peak] [min_peak_s32]\n", argv[0]); return 1; }
    double target = (argc > 3) ? atof(argv[3]) : 18000.0;       /* 输出 S16 目标峰值(~-5dBFS) */
    double min_peak = (argc > 4) ? atof(argv[4]) : 1200000.0;   /* S32 峰值低于此判为无语音 */
    /* max_boost=1 → 退化为纯峰值归一(默认)。低 SNR 下 AGC 收益≈0 甚至负，故默认关；
       >1 时启用分块压缩器(抬轻声块,会连噪声一起抬)。 */
    double max_boost = (argc > 5) ? atof(argv[5]) : 1.0;

    FILE *f = fopen(argv[1], "rb");
    if (!f) { fprintf(stderr, "[micnorm] 打不开 %s\n", argv[1]); return 1; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    if (sz < 44) { fclose(f); return 1; }
    unsigned char *buf = (unsigned char*)malloc(sz);
    if (fread(buf, 1, sz, f) != (size_t)sz) { free(buf); fclose(f); return 1; }
    fclose(f);

    /* 读 fmt：确认采样率与位深 */
    long fmt_len = 0, fmt_off = find_chunk(buf, sz, "fmt ", &fmt_len);
    int bits = 32, rate = 16000, ch = 1;
    if (fmt_off >= 0) {
        ch   = buf[fmt_off+2] | (buf[fmt_off+3]<<8);
        rate = buf[fmt_off+4] | (buf[fmt_off+5]<<8) | (buf[fmt_off+6]<<16) | ((long)buf[fmt_off+7]<<24);
        bits = buf[fmt_off+14] | (buf[fmt_off+15]<<8);
    }
    long data_len = 0, data_off = find_chunk(buf, sz, "data", &data_len);
    if (data_off < 0) { free(buf); fprintf(stderr, "[micnorm] 无 data chunk\n"); return 1; }
    if (data_off + data_len > sz) data_len = sz - data_off;
    if (bits != 32) { fprintf(stderr, "[micnorm] 期望 S32 输入，实际 %dbit\n", bits); free(buf); return 1; }

    if (ch < 1) ch = 1;
    int nsamp = data_len / 4 / ch;
    const unsigned char *p = buf + data_off;

    /* 取 ch0 到 float 数组 */
    double *x = (double*)malloc((nsamp > 0 ? nsamp : 1) * sizeof(double));
    double peak = 0;
    for (int i = 0; i < nsamp; i++) {
        const unsigned char *s = p + (long)i * 4 * ch;   /* ch0 */
        int32_t v = (int32_t)(s[0] | (s[1]<<8) | (s[2]<<16) | ((uint32_t)s[3]<<24));
        x[i] = (double)v;
        double a = v < 0 ? -(double)v : (double)v;
        if (a > peak) peak = a;
    }
    if (peak < min_peak) {
        fprintf(stderr, "[micnorm] 信号过弱 peak=%.0f < %.0f，判无语音\n", peak, min_peak);
        free(buf); free(x); return 124;
    }

    /* 分块 AGC：30ms 块，块峰值 → 增益（target/块峰，封顶），静音块用全局基线增益不抬。 */
    int B = rate * 3 / 100;                 /* 30ms 块 */
    if (B < 1) B = 1;
    int nb = (nsamp + B - 1) / B;
    double g_global = target / peak;        /* 全局基线（=旧的峰值归一） */
    double g_max = g_global * max_boost;

    double *bpeak = (double*)malloc((nb > 0 ? nb : 1) * sizeof(double));
    for (int k = 0; k < nb; k++) {
        double mp = 0;
        int st = k * B, en = st + B; if (en > nsamp) en = nsamp;
        for (int i = st; i < en; i++) { double a = x[i] < 0 ? -x[i] : x[i]; if (a > mp) mp = a; }
        bpeak[k] = mp;
    }
    /* 噪声底 = 块峰值 20 分位数 */
    double *srt = (double*)malloc((nb > 0 ? nb : 1) * sizeof(double));
    memcpy(srt, bpeak, nb * sizeof(double));
    qsort(srt, nb, sizeof(double), cmp_d);
    double noise = srt[(int)(nb * 0.2)];
    double speech_thr = noise * 3.0;
    free(srt);

    double *bgain = (double*)malloc((nb > 0 ? nb : 1) * sizeof(double));
    for (int k = 0; k < nb; k++) {
        double g;
        if (bpeak[k] >= speech_thr && bpeak[k] > 0) {
            g = target / bpeak[k];
            if (g < g_global) g = g_global;
            if (g > g_max) g = g_max;
        } else {
            g = g_global;                   /* 静音/间隙：基线，不放大噪声 */
        }
        bgain[k] = g;
    }
    /* 块增益平滑（±2 块移动平均），防抽水/咔哒 */
    double *sg = (double*)malloc((nb > 0 ? nb : 1) * sizeof(double));
    for (int k = 0; k < nb; k++) {
        double s = 0; int c = 0;
        for (int j = k-2; j <= k+2; j++) { if (j >= 0 && j < nb) { s += bgain[j]; c++; } }
        sg[k] = s / c;
    }

    /* 逐样本：在相邻块增益间线性插值后施加 */
    int16_t *out = (int16_t*)malloc((nsamp > 0 ? nsamp : 1) * sizeof(int16_t));
    for (int i = 0; i < nsamp; i++) {
        double pos = (double)i / B - 0.5;   /* 块中心对齐 */
        int k0 = (int)pos; if (k0 < 0) k0 = 0; if (k0 > nb-1) k0 = nb-1;
        int k1 = k0 + 1; if (k1 > nb-1) k1 = nb-1;
        double f = pos - (int)pos; if (f < 0) f = 0;
        double g = sg[k0] * (1.0 - f) + sg[k1] * f;
        double o = x[i] * g;
        if (o > 32767.0) o = 32767.0;
        if (o < -32768.0) o = -32768.0;
        out[i] = (int16_t)(o >= 0 ? o + 0.5 : o - 0.5);
    }
    double gain = g_global;  /* 仅用于日志 */
    free(x); free(bpeak); free(bgain); free(sg);

    FILE *g = fopen(argv[2], "wb");
    if (!g) { fprintf(stderr, "[micnorm] 写不了 %s\n", argv[2]); free(buf); free(out); return 1; }
    uint32_t db = nsamp * 2;
    fwrite("RIFF",1,4,g); put32(g,36+db); fwrite("WAVE",1,4,g);
    fwrite("fmt ",1,4,g); put32(g,16); put16(g,1); put16(g,1);
    put32(g,rate); put32(g,rate*2); put16(g,2); put16(g,16);
    fwrite("data",1,4,g); put32(g,db);
    fwrite(out,2,nsamp,g);
    fclose(g);
    fprintf(stderr, "[micnorm] AGC peak=%.0f noise=%.0f base_gain=%.4f max_gain=%.4f -> %d 样本 @%dHz S16\n",
            peak, noise, g_global, g_max, nsamp, rate);
    (void)gain;
    free(buf); free(out);
    return 0;
}
