// Named operational events around the released one-hour, simultaneous ward kernel.
#include <algorithm>
#include <cmath>
#include <cstring>
#include <vector>

extern "C" void roll28(int, int, int, int, int, const int*, const double*, const int*,
    const double*, const double*, const int*, double*, double*);

namespace {
constexpr int WMAX = 8, NC = 5, NF = 17, NM = 14, NR = 5, H = 4;
constexpr double eps = 1e-9;
enum Census { ED, ACTIVE, READY, DIRTY, INTERNAL };
enum Driver { ARR, RELEASE, REFERRAL, INTERNAL_SHARE, PORT, CLEAN, SEAT, IDE, AS, NEED_I,
              NEED_A, DIVERT, PORT_EXTRA, CLEAN_EXTRA, SEAT_EXTRA };
enum Metric { ED_H, TRANSFER_H, IDE_MIN, AS_MIN, ADMIT, DIRECT, SMR_EXIT, REDIRECT, IN, OUT,
              ARRIVALS, LOAN_H, RECALL_H };
enum Mode { EXIT, ENTER, REPLACE, REDEPLOY, FLEX_I, FLEX_A, LEND, PORTER, CLEANER, SMR, BED };
enum Resource { RIDES, WASHED, IDE_MINUTES, AS_MINUTES, CAPACITY };
constexpr int NCASE = 4, NACT = 6;
constexpr double exit_ide = 8., exit_as = 4., admission_ide = 14., admission_as = 9.;

double occupants(const double *x) { return x[ACTIVE] + x[READY] + x[INTERNAL]; }
double need(const double *f, const double *x, int skill) {
    return (skill == IDE ? 12. : 9.) + f[skill == IDE ? NEED_I : NEED_A] * occupants(x);
}

// Cases are real labels on the existing stocks, identical for every candidate plan.
// Negative result hours distinguish an absent case (-2) from a present pending case (-1).
void one_plan(
    int wcount, int ncase, const double *beds, const int *route, const double *initial,
    const double *tape, const int *morning, const int *cases, const int *act, int nact,
    double *final, double *totals, double *resources, double *delivered, double *requested,
    int *case_hours) {
    double state[WMAX][NC]{}, cap[WMAX]{}, held_ed[WMAX]{}, held_active[WMAX]{};
    std::memcpy(state, initial, wcount * NC * sizeof(double));
    std::copy(beds, beds + wcount, cap);
    std::vector<int> coordinated(ncase, -1);
    std::vector<double> progress(ncase, 0.);
    std::vector<double> seats_left(nact, 1.);
    for (int i = 0; i < ncase; ++i) {
        const int *c = cases + i * NCASE;
        const int w = c[1], field = c[0] == EXIT ? ACTIVE : ED;
        double &held = field == ACTIVE ? held_active[w] : held_ed[w];
        if (state[w][field] - held + eps >= 1.) {
            held += 1.;
            case_hours[i] = -1;
        } else {
            case_hours[i] = -2;
        }
    }
    for (int a = 0; a < nact; ++a) {
        const int *v = act + a * NACT;
        if (v[0] == EXIT || v[0] == ENTER) coordinated[v[3]] = a;
        if (v[0] == EXIT || v[0] == ENTER || v[0] == SMR || v[0] == BED) requested[a] = 1.;
        if (v[0] == BED) { cap[v[1]] += 1.; delivered[a] = 1.; }
    }
    const int noop[12] = {0,-1,-1, 0,-1,-1, 0,-1,-1, 0,-1,-1};
    const int one = 1;
    for (int h = 0; h < H; ++h) {
        const int clock = 12 + h, offset = 4 + h;
        double row[WMAX][NF]{}, port_extra[WMAX]{}, clean_extra[WMAX]{}, ordinary_seats[WMAX]{};
        double newly_admitted[WMAX]{}, named_rides[WMAX]{}, washed[WMAX]{};
        int port_action = -1, clean_action = -1;
        int port_dst = morning[6] == 4 ? morning[7] : -1;
        int clean_dst = morning[9] == 5 ? morning[10] : -1;
        std::memcpy(row, tape + h * wcount * NF, wcount * NF * sizeof(double));
        for (int a = 0; a < nact; ++a) {
            const int *v = act + a * NACT;
            if (clock < v[4] || clock >= v[5]) continue;
            const int mode = v[0], w = v[1];
            if (mode == PORTER) { port_action = a; port_dst = w; }
            if (mode == CLEANER) { clean_action = a; clean_dst = w; }
            if (mode == FLEX_I || mode == REPLACE || mode == FLEX_A) {
                row[w][mode == FLEX_A ? AS : IDE] += 60.;
                delivered[a] += 60.;
                requested[a] += 60.;
            }
        }
        // A newly present external worker can free a previously blocked donor. Transfers
        // use the live census and deduct the exact amount from the sending roster.
        for (int a = 0; a < nact; ++a) {
            const int *v = act + a * NACT;
            if (clock < v[4] || clock >= v[5] || (v[0] != LEND && v[0] != REDEPLOY)) continue;
            const int skill = v[0] == LEND ? IDE : AS, src = v[2], dst = v[1];
            requested[a] += 60.;
            if (row[src][skill] - 60. + eps >= std::max(60., need(row[src], state[src], skill))) {
                row[src][skill] -= 60.;
                row[dst][skill] += 60.;
                delivered[a] += 60.;
                if (skill == IDE) totals[src * NM + LOAN_H] += 1.;
            } else if (skill == IDE) totals[src * NM + RECALL_H] += 1.;
        }
        for (int w = 0; w < wcount; ++w) {
            resources[w * NR + IDE_MINUTES] += row[w][IDE];
            resources[w * NR + AS_MINUTES] += row[w][AS];
            resources[w * NR + CAPACITY] = cap[w];
            if (offset >= 6 && offset < 18 && port_dst == w) port_extra[w] = row[w][PORT_EXTRA];
            if (offset >= 6 && offset < 18 && clean_dst == w) clean_extra[w] = row[w][CLEAN_EXTRA];
            if (offset >= 5 && offset < 18 && morning[3] == 3 && morning[4] == w)
                row[w][SEAT] += row[w][SEAT_EXTRA];
            ordinary_seats[w] = row[w][SEAT];
            row[w][PORT] += port_extra[w];
            row[w][CLEAN] += clean_extra[w];
        }
        if (port_action >= 0) requested[port_action] += port_extra[port_dst];
        if (clean_action >= 0) requested[clean_action] += clean_extra[clean_dst];
        for (int a = 0; a < nact; ++a) {
            const int *v = act + a * NACT;
            if (v[0] == SMR && clock >= v[4] && clock < v[5]) row[v[1]][SEAT] += seats_left[a];
        }
        // One authorised departure is indivisible. Nursing and transport can work on it
        // across successive hours. Each fraction consumes real capacity exactly once.
        for (int i = 0; i < ncase; ++i) {
            const int *c = cases + i * NCASE;
            const int a = coordinated[i], w = c[1];
            if (c[0] != EXIT || case_hours[i] != -1) continue;
            const bool expedited = a >= 0 && clock >= act[a * NACT + 4] && clock < act[a * NACT + 5];
            if (clock < (expedited ? c[2] : c[3])) continue;
            const double served = std::max(0., std::min({1. - progress[i], row[w][PORT],
                (row[w][IDE] - need(row[w], state[w], IDE)) / exit_ide,
                (row[w][AS] - need(row[w], state[w], AS)) / exit_as}));
            progress[i] += served;
            row[w][PORT] -= served;
            row[w][IDE] -= served * exit_ide;
            row[w][AS] -= served * exit_as;
            named_rides[w] += served;
            if (progress[i] + eps >= 1.) {
                state[w][ACTIVE] -= 1.;
                state[w][DIRTY] += 1.;
                held_active[w] -= 1.;
                totals[w * NM + DIRECT] += 1.;
                case_hours[i] = clock + 1;
                if (a >= 0) delivered[a] = 1.;
            }
        }
        // The same cleaning capacity is removed from the background kernel. A bed can
        // receive a named admission this hour only after enough cleaning was delivered.
        for (int w = 0; w < wcount; ++w) {
            washed[w] = std::min(state[w][DIRTY], row[w][CLEAN]);
            state[w][DIRTY] -= washed[w];
            row[w][CLEAN] = 0.;
            resources[w * NR + WASHED] += washed[w];
        }
        for (int i = 0; i < ncase; ++i) {
            const int *c = cases + i * NCASE;
            const int a = coordinated[i], w = c[1];
            if (c[0] != ENTER || case_hours[i] != -1) continue;
            const bool expedited = a >= 0 && clock >= act[a * NACT + 4] && clock < act[a * NACT + 5];
            if (clock < (expedited ? c[2] : c[3])) continue;
            if (cap[w] - occupants(state[w]) - state[w][DIRTY] + eps < 1.
                || row[w][IDE] + eps < need(row[w], state[w], IDE) + row[w][NEED_I] + admission_ide
                || row[w][AS] + eps < need(row[w], state[w], AS) + row[w][NEED_A] + admission_as) continue;
            state[w][ED] -= 1.;
            state[w][ACTIVE] += 1.;
            held_ed[w] -= 1.;
            newly_admitted[w] += 1.;
            row[w][IDE] -= admission_ide;
            row[w][AS] -= admission_as;
            totals[w * NM + ADMIT] += 1.;
            case_hours[i] = clock + 1;
            if (a >= 0) delivered[a] = 1.;
        }
        double step[WMAX][NM]{}, end[WMAX][NC]{};
        for (int w = 0; w < wcount; ++w) {
            state[w][ED] = std::max(0., state[w][ED] - held_ed[w]);
            // Keep the protected patients physically present for bed and nursing equations.
            // Ordinary clearance applies only to the remaining active census.
            if (state[w][ACTIVE] > 0.) row[w][RELEASE] *= std::max(0.,
                state[w][ACTIVE] - held_active[w] - newly_admitted[w]) / state[w][ACTIVE];
        }
        roll28(wcount, 1, 1, offset, 1, &one, cap, route, &state[0][0], &row[0][0],
               noop, &step[0][0], &end[0][0]);
        for (int w = 0; w < wcount; ++w) {
            end[w][ED] += held_ed[w];
            step[w][ED_H] += held_ed[w];
            for (int m = 0; m < NM; ++m) totals[w * NM + m] += step[w][m];
            const double rides = named_rides[w] + step[w][SMR_EXIT] + step[w][OUT];
            resources[w * NR + RIDES] += rides;
            if (port_action >= 0 && w == port_dst)
                delivered[port_action] += std::min(port_extra[w],
                    std::max(0., rides - tape[(h * wcount + w) * NF + PORT]));
            if (clean_action >= 0 && w == clean_dst)
                delivered[clean_action] += std::min(clean_extra[w],
                    std::max(0., washed[w] - tape[(h * wcount + w) * NF + CLEAN]));
        }
        for (int a = 0; a < nact; ++a) {
            const int *v = act + a * NACT;
            if (v[0] != SMR || clock < v[4] || clock >= v[5]) continue;
            const int w = v[1];
            const double used = std::min(seats_left[a], std::max(0., step[w][SMR_EXIT] - ordinary_seats[w]));
            seats_left[a] -= used;
            delivered[a] += used;
        }
        std::memcpy(state, end, wcount * NC * sizeof(double));
    }
    std::memcpy(final, state, wcount * NC * sizeof(double));
}
} // namespace

extern "C" void joint28(int wards, int nplans, int ncase, const double *beds, const int *route,
    const double *initial, const double *drivers, const int *morning, const int *cases,
    const int *offsets, const int *actions, double *final, double *metrics, double *resources,
    double *delivered, double *requested, int *case_hours) {
    for (int p = 0; p < nplans; ++p)
        one_plan(wards, ncase, beds, route, initial, drivers, morning, cases,
            actions + offsets[p] * NACT, offsets[p+1] - offsets[p], final + p * wards * NC,
            metrics + p * wards * NM, resources + p * wards * NR, delivered + offsets[p],
            requested + offsets[p], case_hours + p * ncase);
}
