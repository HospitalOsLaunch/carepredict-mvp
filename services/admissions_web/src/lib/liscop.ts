import { useMutation, useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { BED_BLOCK_REASONS } from "../api/types_liscop";
import type {
  Bed,
  BedAction,
  BedBlockReason,
  BedBoard,
  BedStatus,
  BoardingSeries,
  EdCensus,
  EdSnapshot,
  TensionDeclaration,
  TensionStatus
} from "../api/types_liscop";

const REFRESH_MS = 60_000;

function query(siteId: number | null): string {
  return siteId === null ? "" : `?site_id=${siteId}`;
}

const BED_ACTION_KEY = ["bed-action"];

export function useBedBoard() {
  const client = useQueryClient();
  return useQuery({
    queryKey: ["beds"],
    queryFn: () => api<BedBoard>("/beds"),
    // Not while a bed action is being saved: an answer computed before it would put the tile back.
    refetchInterval: () => (client.isMutating({ mutationKey: BED_ACTION_KEY }) ? false : REFRESH_MS)
  });
}

export interface BedActionInput {
  id: number;
  action: BedAction;
  reason?: BedBlockReason | "";
  note?: string;
}

/** The status each action leads to (TRANSITIONS on the API). */
const TARGET: Record<BedAction, BedStatus> = {
  nettoye: "libre",
  bloquer: "bloque",
  debloquer: "libre",
  reserver: "reserve",
  annuler_reservation: "libre"
};

function mapBed(board: BedBoard, id: number, change: (bed: Bed) => Bed): BedBoard {
  return {
    ...board,
    sites: board.sites.map((site) => ({
      ...site,
      units: site.units.map((unit) => ({
        ...unit,
        rooms: unit.rooms.map((room) => ({ ...room, beds: room.beds.map((bed) => (bed.id === id ? change(bed) : bed)) }))
      }))
    }))
  };
}

/** The board as it will be once the action is saved, for the tile only (the counts follow the API). */
export function applyBedAction(board: BedBoard, { id, action, reason, note }: BedActionInput): BedBoard {
  return mapBed(board, id, (bed) => {
    const label = reason ? BED_BLOCK_REASONS[reason] : null;
    const status = TARGET[action];
    return {
      ...bed,
      status,
      usable: status === "libre",
      status_reason: action === "bloquer" && label ? (note ? `${label} : ${note}` : label) : null
    };
  });
}

function findBed(board: BedBoard | undefined, id: number): Bed | undefined {
  for (const site of board?.sites ?? [])
    for (const unit of site.units)
      for (const room of unit.rooms) {
        const bed = room.beds.find((b) => b.id === id);
        if (bed) return bed;
      }
  return undefined;
}

/**
 * A bed action shown at once (règle 14 de l'audit) : the tile takes its new status before
 * the API answers. If the API refuses (someone else changed the bed meanwhile, network
 * lost), only that bed goes back to what it was: another action in flight is kept.
 */
export function useBedAction() {
  const client = useQueryClient();
  return useMutation({
    mutationKey: BED_ACTION_KEY,
    mutationFn: ({ id, action, reason, note }: BedActionInput) =>
      api(`/beds/${id}`, {
        method: "PATCH",
        json: { action, ...(reason ? { reason } : {}), ...(note ? { note } : {}) }
      }),
    onMutate: async (input) => {
      await client.cancelQueries({ queryKey: ["beds"] });
      const before = findBed(client.getQueryData<BedBoard>(["beds"]), input.id);
      client.setQueryData<BedBoard>(["beds"], (board) => (board ? applyBedAction(board, input) : board));
      return { before };
    },
    onError: (_error, input, context) => {
      const before = context?.before;
      if (before) client.setQueryData<BedBoard>(["beds"], (board) => (board ? mapBed(board, input.id, () => before) : board));
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["beds"] });
      void client.invalidateQueries({ queryKey: ["tension-status"] });
    }
  });
}

/** The beds whose action is being saved (a tile shows it). */
export function usePendingBeds(): Set<number> {
  const ids = useMutationState({
    filters: { mutationKey: BED_ACTION_KEY, status: "pending" },
    select: (m) => (m.state.variables as BedActionInput | undefined)?.id
  });
  return new Set(ids.filter((id): id is number => id !== undefined));
}

export function useEdCensus(siteId: number | null) {
  return useQuery({
    queryKey: ["ed-census", siteId],
    queryFn: () => api<EdCensus>(`/ed/census${query(siteId)}`),
    refetchInterval: REFRESH_MS
  });
}

export function useBoarding(siteId: number | null, days = 90) {
  const params = new URLSearchParams({ days: String(days) });
  if (siteId !== null) params.set("site_id", String(siteId));
  return useQuery({
    queryKey: ["ed-boarding", siteId, days],
    queryFn: () => api<BoardingSeries>(`/ed/boarding?${params.toString()}`)
  });
}

export function useSnapshots(siteId: number | null) {
  return useQuery({
    queryKey: ["ed-snapshots", siteId],
    queryFn: () => api<EdSnapshot[]>(`/ed/snapshots${query(siteId)}`)
  });
}

export function useTensionStatus(siteId: number | null) {
  return useQuery({
    queryKey: ["tension-status", siteId],
    queryFn: () => api<TensionStatus>(`/tension/status${query(siteId)}`),
    refetchInterval: REFRESH_MS
  });
}

export function useDeclarations() {
  return useQuery({
    queryKey: ["tension-declarations"],
    queryFn: () => api<TensionDeclaration[]>("/tension/declarations")
  });
}

/** Any write on the emergency / tension side refreshes every view that depends on it. */
export function useEdWrite<T>(path: string, method: "POST" | "PATCH" = "POST") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ body, id }: { body: T; id?: number }) =>
      api(id === undefined ? path : `${path}/${id}`, { method, json: body }),
    onSuccess: () => {
      for (const key of ["ed-census", "ed-boarding", "ed-snapshots", "tension-status", "tension-declarations"]) {
        void client.invalidateQueries({ queryKey: [key] });
      }
    }
  });
}
