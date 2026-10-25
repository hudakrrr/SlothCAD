/* Original CPU triangle rasterizer. Four subpixel samples provide 2x2 SSAA.
   Caller owns reusable buffers. No kernel geometry or Python APIs here. */
#include <stddef.h>
#include <stdint.h>

#ifdef SLOTHCAD_FREESTANDING
/* The prebuilt Windows DLL links against no C runtime at all, so it works on any
   Windows 10/11 machine without Visual C++ redistributables. These replacements
   only need to be exact for the finite, screen-sized values used below. */
#define INFINITY __builtin_inf()
static double sc_fabs(double x){return x<0?-x:x;}
static double sc_fmin(double a,double b){return a<b?a:b;}
static double sc_fmax(double a,double b){return a>b?a:b;}
static double sc_floor(double x){
    if (!(x>-4.5e15 && x<4.5e15)) return x;
    double t=(double)(long long)x; return t>x?t-1.0:t;
}
static double sc_ceil(double x){
    if (!(x>-4.5e15 && x<4.5e15)) return x;
    double t=(double)(long long)x; return t<x?t+1.0:t;
}
#define fabs sc_fabs
#define fmin sc_fmin
#define fmax sc_fmax
#define floor sc_floor
#define ceil sc_ceil
int _fltused=0;
#else
#include <math.h>
#endif

#if defined(_WIN32)
#define SLOTHCAD_EXPORT __declspec(dllexport)
#else
#define SLOTHCAD_EXPORT
#endif

SLOTHCAD_EXPORT int slothcad_render(const double *xy, const double *vz, const int32_t *tri,
                 const int32_t *faces, const uint8_t *colors, int count,
                 int width, int height, int factor,
                 float *high_z, int32_t *high_id, uint8_t *high_rgb,
                 uint8_t *rgba, float *out_z, int32_t *out_id) {
    if (width<=0 || height<=0 || (factor!=1 && factor!=2)) return -1;
    int sw=width*factor, sh=height*factor;
    size_t samples=(size_t)sw*sh;
    for (size_t j=0;j<samples;j++) { high_z[j]=-INFINITY; high_id[j]=-1; }
    for (int i=0;i<count;i++) {
        int ia=tri[3*i], ib=tri[3*i+1], ic=tri[3*i+2];
        double ax=xy[2*ia]*factor, ay=xy[2*ia+1]*factor;
        double bx=xy[2*ib]*factor, by=xy[2*ib+1]*factor;
        double cx=xy[2*ic]*factor, cy=xy[2*ic+1]*factor;
        double den=(by-cy)*(ax-cx)+(cx-bx)*(ay-cy);
        if (fabs(den)<1e-12) continue;
        double minx=fmin(ax,fmin(bx,cx)), maxx=fmax(ax,fmax(bx,cx));
        double miny=fmin(ay,fmin(by,cy)), maxy=fmax(ay,fmax(by,cy));
        if (maxx<0 || maxy<0 || minx>=sw || miny>=sh) continue;
        int x0=(int)floor(fmax(0,minx)),x1=(int)ceil(fmin(sw-1,maxx));
        int y0=(int)floor(fmax(0,miny)),y1=(int)ceil(fmin(sh-1,maxy));
        double ux=(by-cy)/den, uy=(cx-bx)/den;
        double wx=(cy-ay)/den, wy=(ax-cx)/den;
        double zax=vz[ia]-vz[ic], zbx=vz[ib]-vz[ic];
        double zx=ux*zax+wx*zbx;
        for (int y=y0;y<=y1;y++) {
            double u=ux*(x0+.5-cx)+uy*(y+.5-cy);
            double w=wx*(x0+.5-cx)+wy*(y+.5-cy);
            double z=u*zax+w*zbx+vz[ic];
            size_t idx=(size_t)y*sw+x0;
            for (int x=x0;x<=x1;x++,idx++,u+=ux,w+=wx,z+=zx) {
                if (u>=-1e-7 && w>=-1e-7 && u+w<=1+1e-7 && z>high_z[idx]) {
                    high_z[idx]=(float)z; high_id[idx]=faces[i];
                    high_rgb[3*idx]=colors[3*i];high_rgb[3*idx+1]=colors[3*i+1];high_rgb[3*idx+2]=colors[3*i+2];
                }
            }
        }
    }
    for (int y=0;y<height;y++) for (int x=0;x<width;x++) {
        size_t idx=(size_t)y*width+x;
        unsigned r=0,g=0,b=0,n=0;float nearest=-INFINITY;int face=-1;
        for (int sy=0;sy<factor;sy++) for (int sx=0;sx<factor;sx++) {
            size_t j=(size_t)(y*factor+sy)*sw+x*factor+sx;
            if (high_id[j]>=0) {
                r+=high_rgb[3*j];g+=high_rgb[3*j+1];b+=high_rgb[3*j+2];n++;
                if (high_z[j]>nearest) {nearest=high_z[j];face=high_id[j];}
            }
        }
        rgba[4*idx]=n?(uint8_t)(r/n):0;rgba[4*idx+1]=n?(uint8_t)(g/n):0;
        rgba[4*idx+2]=n?(uint8_t)(b/n):0;rgba[4*idx+3]=(uint8_t)((n*255+factor*factor/2)/(factor*factor));
        out_z[idx]=nearest;out_id[idx]=face;
    }
    return 0;
}
