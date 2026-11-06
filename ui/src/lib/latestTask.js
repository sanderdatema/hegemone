// Alleen de nieuwste laadopdracht mag de zichtbare toestand bijwerken.
// Ook fouten en het laadicoon van oude opdrachten worden genegeerd (BETON-492).
export function latestTask(task, { apply, error, settled }) {
  let sequence = 0;
  return async (...args) => {
    const mine = ++sequence;
    try {
      const result = await task(...args);
      if (mine === sequence) apply(result);
    } catch (e) {
      if (mine === sequence) error(e);
    } finally {
      if (mine === sequence) settled();
    }
  };
}
