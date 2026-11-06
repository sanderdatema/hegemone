import {it, expect} from 'vitest';
import {workloadLabel, workloadMeta, relationLabel} from './labels.js';
import {activeFilterChips} from './viewState.js';

it('houdt API-waarden gelijk terwijl de presentatie wisselt', () => {
  expect(workloadLabel('heavy', 'en')).toBe('Heavy');
  expect(workloadLabel('heavy', 'nl')).toBe('Zwaar');
  expect(workloadMeta('heavy', 'en').short).toBe('H');
  expect(relationLabel('blocked_by', 'en')).toBe('blocked by');
  expect(relationLabel('blocked_by', 'nl')).toBe('geblokkeerd door');
  expect(activeFilterChips({workload: 'heavy'}, 'en')).toEqual([{key:'workload',field:'Workload',value:'Heavy'}]);
  expect(activeFilterChips({due: 'week'}, 'en')).toEqual([{key:'due',field:'Due date',value:'This week'}]);
});
