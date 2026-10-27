import assert from "node:assert/strict";
import test from "node:test";
import {
  buildProductionComparison,
  filterRecordsByPeriod,
  normalizeDateKey,
  operatorBarWidths,
} from "./productionAnalytics.js";

const productions = [
  { data: "2026-10-24", secao: "Montagem", operador: "Operador A", quantidade: 20, usuarioRe: "RE-101" },
  { data: "2026-10-24", secao: "Montagem", operador: "Operador A", quantidade: 13, usuarioRe: "RE-101" },
  { data: "2026-10-24", secao: "Montagem", operador: "Operador B", quantidade: 33, usuarioRe: "RE-202" },
  { data: "2026-10-23", secao: "Montagem", operador: "Operador A", quantidade: 5, usuarioRe: "RE-101" },
  { data: "2026-10-24", secao: "Pintura", operador: "Operador B", quantidade: 12, usuarioRe: "RE-202" },
];
const goals = [
  { secao: "Montagem", quantidade: 33 },
  { secao: "Pintura", quantidade: 20 },
];

test("daily comparison sums an operator's records without merging different names that share an RE", () => {
  const records = [
    ...productions,
    { data: "2026-10-24", secao: "Montagem", operador: "Operador C", quantidade: 9, usuarioRe: "RE-101" },
    { data: "2026-10-24", secao: "Montagem", operador: "Operador C", quantidade: 4, usuarioRe: "RE-101" },
  ];
  const result = buildProductionComparison(records, goals, "day", "2026-10-24");

  assert.deepEqual(
    result.operators.map(({ operador, RE, quantidade, meta }) => ({ operador, RE, quantidade, meta })),
    [
      { operador: "Operador A", RE: "RE-101", quantidade: 33, meta: 33 },
      { operador: "Operador B", RE: "RE-202", quantidade: 33, meta: 33 },
      { operador: "Operador C", RE: "RE-101", quantidade: 13, meta: 33 },
      { operador: "Operador B", RE: "RE-202", quantidade: 12, meta: 20 },
    ],
  );
  assert.deepEqual(result.sections, [
    { secao: "Montagem", quantidade: 79 },
    { secao: "Pintura", quantidade: 12 },
  ]);
  assert.deepEqual(result.remainingPiecesByType, []);
});

test("monthly comparison sums the month while keeping the daily target unchanged", () => {
  const result = buildProductionComparison(productions, goals, "month", "2026-10");

  assert.equal(result.operators.find((item) => item.RE === "RE-101").quantidade, 38);
  assert.equal(result.operators.find((item) => item.RE === "RE-101").meta, 33);
  assert.deepEqual(result.sections, [
    { secao: "Montagem", quantidade: 71 },
    { secao: "Pintura", quantidade: 12 },
  ]);
});

test("comparison chart uses the latest goal for the operator's section", () => {
  const result = buildProductionComparison(
    [{ data: "2026-10-24", secao: "Bandagem", operador: "Operador A", usuarioRe: "RE-101", quantidade: 25 }],
    [{ secao: "Bandagem", quantidade: 23 }],
    "day",
    "2026-10-24",
  );

  assert.equal(result.operators[0].meta, 23);
});

test("selected date with no production records returns an empty comparison", () => {
  const result = buildProductionComparison(productions, goals, "day", "2026-10-22");

  assert.deepEqual(result.operators, []);
  assert.deepEqual(result.sections, []);
  assert.deepEqual(result.remainingPiecesByType, []);
});

test("operators without production records are not included in production comparison", () => {
  const result = buildProductionComparison(
    [],
    goals,
    "day",
    "2026-10-24",
    [],
    ["acabamento"],
  );

  assert.deepEqual(result.operators, []);
  assert.deepEqual(result.sections, []);
});

test("operator production and goal bars use a shared quantity scale", () => {
  const bars = operatorBarWidths(40, 100, 120);
  assert.ok(Math.abs(bars.produced - 100 / 3) < 0.000001);
  assert.ok(Math.abs(bars.target - 250 / 3) < 0.000001);
  assert.deepEqual(operatorBarWidths(20, 20, 50), { produced: 40, target: 40 });
  assert.deepEqual(operatorBarWidths(125, 100, 125), { produced: 100, target: 80 });
  assert.deepEqual(operatorBarWidths(30, 0, 60), { produced: 50, target: 0 });
  assert.deepEqual(operatorBarWidths(45, 0, 60), { produced: 75, target: 0 });
  assert.deepEqual(operatorBarWidths(50, 20, 50), { produced: 100, target: 40 });
});

test("production dates in ISO and Brazilian formats match the selected day", () => {
  assert.equal(normalizeDateKey("2026-10-24T12:30:00Z"), "2026-10-24");
  assert.equal(normalizeDateKey("24/10/2026"), "2026-10-24");

  const result = buildProductionComparison(
    [{ data: "24/10/2026", secao: "Montagem", operador: "Operador A", usuarioRe: "RE-101", quantidade: 42 }],
    goals,
    "day",
    "2026-10-24",
  );
  assert.equal(result.sections.find((item) => item.secao === "Montagem").quantidade, 42);
});

test("selected day and month filters only include matching production and piece records", () => {
  const records = [
    { data: "2026-10-24T10:00:00Z" },
    { data: "23/10/2026 10:00:00" },
    { data: "2026-09-24" },
  ];

  assert.deepEqual(filterRecordsByPeriod(records, "day", "2026-10-24"), [records[0]]);
  assert.deepEqual(
    filterRecordsByPeriod(records, "month", "2026-10"),
    [records[0], records[1]],
  );
});

test("remaining piece types sum each operator's latest snapshot within the selected period", () => {
  const result = buildProductionComparison(
    [
      { data: "2026-10-24", secao: "Montagem", operador: "Operador A", usuarioRe: "RE-101", quantidade: 15 },
      { data: "2026-10-20", secao: "Pintura", operador: "Operador B", usuarioRe: "RE-202", quantidade: 8 },
      { data: "2026-10-25", secao: "Corte", operador: "Operador B", usuarioRe: "RE-202", quantidade: 12 },
    ],
    goals,
    "day",
    "2026-10-24",
    [
      { id: "old-a", data: "2026-10-23", usuarioRe: "RE-101", acabamento: 100 },
      { id: "new-a", data: "2026-10-24", usuarioRe: "RE-101", acabamento: 2 },
      { id: "b", data: "2026-10-24", usuarioRe: "RE-202", solda: 4 },
      { id: "c", data: "2026-10-24", usuarioRe: "RE-303", solda: 6 },
    ],
    ["acabamento", "solda"],
  );

  assert.deepEqual(result.sections, [
    { secao: "Montagem", quantidade: 15 },
  ]);
  assert.deepEqual(result.remainingPiecesByType, [
    { field: "solda", quantidade: 10 },
    { field: "acabamento", quantidade: 2 },
  ]);
  assert.equal(
    result.remainingPiecesByType.reduce((total, item) => total + item.quantidade, 0),
    12,
  );
});

test("remaining piece categories use document fields without treating date as a category", () => {
  const result = buildProductionComparison(
    [
      { data: "2026-10-24", secao: "Montagem", operador: "Operador A", usuarioRe: "RE-101", quantidade: 15 },
    ],
    goals,
    "day",
    "2026-10-24",
    [
      {
        id: "piece-a",
        data: "2026-10-24",
        usuarioRe: "RE-101",
        secao: "Pintura",
        acabamento: 3,
        amarracao: 4,
        bandagem: 5,
        ligacao: 6,
        prenca: 7,
        solda: 8,
      },
    ],
    ["acabamento", "amarracao", "bandagem", "ligacao", "prenca", "solda"],
  );

  assert.deepEqual(result.remainingPiecesByType, [
    { field: "solda", quantidade: 8 },
    { field: "prenca", quantidade: 7 },
    { field: "ligacao", quantidade: 6 },
    { field: "bandagem", quantidade: 5 },
    { field: "amarracao", quantidade: 4 },
    { field: "acabamento", quantidade: 3 },
  ]);
  assert.equal(result.sections.find((item) => item.secao === "Montagem").quantidade, 15);
});
