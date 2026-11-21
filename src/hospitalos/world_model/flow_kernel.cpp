// Simultaneous finite-bed transitions on a directed ward network, one hour per step.
// Retains the parent weekly engine's nursing admission, dirty-bed, and donor-floor equations.
#include <algorithm>
#include <cmath>
#include <cstring>

namespace {
constexpr int max_wards = 8;
enum Census { ED, ACTIVE, READY, DIRTY, INTERNAL_READY, S };
enum Drivers { ARR, RELEASE, REFERRAL, INTERNAL_SHARE, PORT, CLEAN, SMR, IDE, AS, IDE_NEED,
               AS_NEED, DIVERT, PORT_EXTRA, CLEAN_EXTRA, SMR_EXTRA, IDE_EXTRA, AS_EXTRA, D };
enum Metrics { ED_H, TRANSFER_H, IDE_MIN, AS_MIN, ADMIT, DIRECT, SMR_EXIT, REDIRECT,
               INTERNAL_IN, INTERNAL_OUT, ARRIVALS, LOAN, RECALL, DONOR_VIOLATION, M };
}

extern "C" void roll28(int wards, int nplans, int schedule_days, int boundary_offset,
                       int nhorizons, const int* cutoffs, const double* beds, const int* route,
                       const double* initial, const double* tape, const int* plans,
                       double* cum_metrics, double* final_states) {
    for (int p=0; p<nplans; ++p) {
        double state[max_wards][S] = {};
        double totals[max_wards][M] = {};
        std::memcpy(state, initial, wards*S*sizeof(double));
        int snapshot = 0;
        for (int t=0; t<cutoffs[nhorizons-1]; ++t) {
            const int day=(t+boundary_offset)/24;
            const int hour=(t+boundary_offset)%24;
            const int* actions=plans+((p*schedule_days+day)*4)*3;
            const bool staff_window = hour>=10 && hour<20;
            const bool seat_window = hour>=5 && hour<18;
            const bool crew_window = hour>=6 && hour<18;
            const double* row = tape+t*wards*D;
            double ide[max_wards], as[max_wards], need_i[max_wards], need_a[max_wards];
            double direct[max_wards], smr[max_wards], pending[max_wards], room[max_wards];
            double allowance[max_wards], internal[max_wards], received[max_wards]={};
            double incoming[max_wards]={}, cleared[max_wards], washed[max_wards];
            for (int w=0; w<wards; ++w) {
                const double* f=row+w*D;
                const double census=state[w][ACTIVE]+state[w][READY]+state[w][INTERNAL_READY];
                ide[w]=f[IDE]; as[w]=f[AS];
                need_i[w]=12. + f[IDE_NEED]*census;
                need_a[w]=9. + f[AS_NEED]*census;
            }
            if (staff_window) {
                const int kind=actions[0], dst=actions[1], src=actions[2];
                if(kind==1) ide[dst]+=row[dst*D+IDE_EXTRA];
                if(kind==2) as[dst]+=row[dst*D+AS_EXTRA];
                if(kind==6) {
                    const double reserve=std::max(60.,need_i[src]);
                    if(ide[src]-60.+1e-9>=reserve) {
                        ide[src]-=60.; ide[dst]+=60.; totals[src][LOAN]+=1.;
                        totals[src][DONOR_VIOLATION]+=(ide[src]+1e-9<reserve);
                    } else { totals[src][RECALL]+=1.; }
                }
            }
            for(int w=0; w<wards; ++w) {
                const double* f=row+w*D;
                const double seats=f[SMR]+(seat_window && actions[3]==3 && actions[4]==w ? f[SMR_EXTRA]:0.);
                const double port=f[PORT]+(crew_window && actions[6]==4 && actions[7]==w ? f[PORT_EXTRA]:0.);
                const double clean=f[CLEAN]+(crew_window && actions[9]==5 && actions[10]==w ? f[CLEAN_EXTRA]:0.);
                // One porter serves both routes; allocate capacity proportionally then use spare for SMR.
                const double can_smr=std::min(seats,state[w][READY]);
                const double can_internal=state[w][INTERNAL_READY];
                const double total=can_smr+can_internal;
                const double ratio=total>0 ? std::min(1.,port/total) : 0.;
                smr[w]=can_smr*ratio;
                pending[w]=can_internal*ratio;
                incoming[route[w]]+=pending[w];
                washed[w]=std::min(state[w][DIRTY],clean);
                cleared[w]=state[w][ACTIVE]*f[RELEASE];
                direct[w]=cleared[w]*(1.-f[REFERRAL]-f[INTERNAL_SHARE]);
                room[w]=std::max(0.,beds[w]-state[w][ACTIVE]-state[w][READY]-state[w][INTERNAL_READY]
                                      -state[w][DIRTY]+washed[w]);
                allowance[w]=std::max(0.,std::min((ide[w]-need_i[w])/14.,(as[w]-need_a[w])/9.));
            }
            for(int w=0; w<wards; ++w) {
                const int dst=route[w];
                const double accessible=std::min(room[dst],allowance[dst]);
                const double ratio=incoming[dst]>0 ? std::min(1.,accessible/incoming[dst]) : 0.;
                internal[w]=pending[w]*ratio;
                received[dst]+=internal[w];
                const double* f=row+w*D;
                // A blocked internal transfer releases the unused transport opportunity that hour.
                smr[w]+=std::min(pending[w]-internal[w],
                    std::max(0.,std::min(state[w][READY],f[SMR]+(
                    seat_window && actions[3]==3 && actions[4]==w ? f[SMR_EXTRA]:0.))-smr[w]));
            }
            for(int w=0; w<wards; ++w) {
                const double* f=row+w*D;
                const double q=state[w][ED]+f[ARR];
                const double admitted=std::min(q,std::max(0.,std::min(room[w],allowance[w])-received[w]));
                const double left=q-admitted;
                // Persistent waits may be reoriented to another hospital. These departures are separately audited.
                const double redirect=std::max(0.,left-.20*beds[w])*f[DIVERT];
                state[w][ED]=left-redirect;
                state[w][ACTIVE]+=received[w]+admitted-cleared[w];
                state[w][READY]+=cleared[w]*f[REFERRAL]-smr[w];
                state[w][INTERNAL_READY]+=cleared[w]*f[INTERNAL_SHARE]-internal[w];
                state[w][DIRTY]+=direct[w]+smr[w]+internal[w]-washed[w];
                double* z=totals[w];
                z[ED_H]+=state[w][ED]; z[TRANSFER_H]+=state[w][READY]+state[w][INTERNAL_READY];
                z[IDE_MIN]+=std::max(0.,need_i[w]+14.*(received[w]+admitted)-ide[w]);
                z[AS_MIN]+=std::max(0.,need_a[w]+9.*(received[w]+admitted)-as[w]);
                z[ADMIT]+=admitted; z[DIRECT]+=direct[w]; z[SMR_EXIT]+=smr[w]; z[REDIRECT]+=redirect;
                z[INTERNAL_IN]+=received[w]; z[INTERNAL_OUT]+=internal[w]; z[ARRIVALS]+=f[ARR];
            }
            if(t+1==cutoffs[snapshot]) {
                const int off=(p*nhorizons+snapshot)*wards;
                std::memcpy(cum_metrics+off*M,totals,wards*M*sizeof(double));
                std::memcpy(final_states+off*S,state,wards*S*sizeof(double));
                ++snapshot;
            }
        }
    }
}
