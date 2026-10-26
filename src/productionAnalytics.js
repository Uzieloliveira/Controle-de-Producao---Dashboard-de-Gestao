export function sectionKey(value) {
  return String(value || "").trim().toLocaleLowerCase("pt-BR");
}

export function operatorBarWidths(quantity, goal, productionScale) {
  const scale = Math.max(1, productionScale);
  return {
    produced: Math.min(100, quantity / scale * 100),
    target: Math.min(100, goal / scale * 100),
  };
}

export function normalizeDateKey(value) {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toISOString().slice(0, 10);
  }

  const date = String(value || "").trim();
  const isoDate = date.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (isoDate) {
    return `${isoDate[1]}-${isoDate[2].padStart(2, "0")}-${isoDate[3].padStart(2, "0")}`;
  }

  const localizedDate = date.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})/);
  if (localizedDate) {
    return `${localizedDate[3]}-${localizedDate[2].padStart(2, "0")}-${localizedDate[1].padStart(2, "0")}`;
  }

  return "";
}

export function filterRecordsByPeriod(records, mode, selectedDate) {
  const selectedDateKey = normalizeDateKey(selectedDate);
  const selectedMonth = String(selectedDate || "").match(/^(\d{4})-(\d{1,2})/);
  const periodKey = mode === "day"
    ? selectedDateKey
    : selectedMonth
      ? `${selectedMonth[1]}-${selectedMonth[2].padStart(2, "0")}`
      : selectedDateKey.slice(0, 7);

  return records.filter((record) => {
    const recordDate = normalizeDateKey(record.data);
    const recordPeriod = mode === "day" ? recordDate : recordDate.slice(0, 7);
    return recordPeriod && recordPeriod === periodKey;
  });
}

function productionOperatorKey(record) {
  const section = String(record.secao || "").trim() || "Seção não informada";
  const operator = String(record.operador || "").trim();
  const operatorRe = String(record.usuarioRe || "").trim();
  const operatorId = operatorNameKey(operator) || operatorRe || "operador não informado";
  return `${sectionKey(section)}\0${operatorId}`;
}

function operatorNameKey(value) {
  return String(value || "").trim().toLocaleLowerCase("pt-BR");
}

export function buildProductionComparison(
  productions,
  goals,
  mode,
  selectedDate,
  remainingPieces = [],
  pieceFields = [],
) {
  const periodProductions = filterRecordsByPeriod(productions, mode, selectedDate);
  const goalsBySection = new Map(
    goals.map((item) => [sectionKey(item.secao), Number(item.quantidade) || 0]),
  );
  const operators = new Map();
  const productionSections = new Map();

  for (const record of productions) {
    const section = String(record.secao || "").trim() || "Seção não informada";
    const operator = String(record.operador || "").trim() || "Operador não informado";
    const operatorRe = String(record.usuarioRe || "").trim();
    const sectionId = sectionKey(section);
    const operatorId = productionOperatorKey(record);
    const operatorRow = operators.get(operatorId) || {
      secao: section,
      operador: operator,
      RE: operatorRe,
      quantidade: 0,
      meta: goalsBySection.get(sectionId) || 0,
    };
    operators.set(operatorId, operatorRow);
  }

  for (const record of periodProductions) {
    const operatorId = productionOperatorKey(record);
    const operatorRow = operators.get(operatorId);
    if (operatorRow) {
      operatorRow.quantidade += Number(record.quantidade) || 0;
    }
  }

  for (const operator of operators.values()) {
    const sectionId = sectionKey(operator.secao);
    const sectionRow = productionSections.get(sectionId) || {
      secao: operator.secao,
      quantidade: 0,
    };
    sectionRow.quantidade += operator.quantidade;
    productionSections.set(sectionId, sectionRow);
  }

  const latestPiecesByOperator = new Map();
  for (const record of filterRecordsByPeriod(remainingPieces, mode, selectedDate)) {
    const operatorRe = String(record.usuarioRe || "").trim();
    const recordKey = operatorRe || String(record.id || "");
    if (!recordKey) continue;

    const current = latestPiecesByOperator.get(recordKey);
    const recordDate = normalizeDateKey(record.data);
    const currentDate = normalizeDateKey(current?.data);
    const recordSortKey = `${recordDate}\0${String(record.data || "")}\0${String(record.id || "")}`;
    const currentSortKey = current
      ? `${currentDate}\0${String(current.data || "")}\0${String(current.id || "")}`
      : "";
    if (!current || recordSortKey > currentSortKey) {
      latestPiecesByOperator.set(recordKey, record);
    }
  }

  const latestPieceRecords = [...latestPiecesByOperator.values()];
  const remainingPiecesByType = pieceFields.map((field) => ({
    field,
    quantidade: latestPieceRecords.reduce(
      (total, record) => total + (Number(record[field]) || 0),
      0,
    ),
  }));

  return {
    operators: [...operators.values()].sort(
      (a, b) => a.secao.localeCompare(b.secao, "pt-BR") || a.operador.localeCompare(b.operador, "pt-BR"),
    ),
    sections: [...productionSections.values()]
      .sort((a, b) => b.quantidade - a.quantidade),
    remainingPiecesByType: remainingPiecesByType.sort(
      (a, b) => b.quantidade - a.quantidade,
    ),
  };
}
