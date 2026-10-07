import { describe, expect, it } from 'vitest';
import { createSidebarExpansionStore } from './sidebarExpansionStore';

describe('sidebar expansion preferences', () => {
  const storage = () => {
    const values = new Map();
    return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  };
  it('keeps user and institution groups collapsed after remounting and reloading', () => {
    const disk = storage();
    const first = createSidebarExpansionStore(() => disk);
    first.set('alice', { 'owner-Bob': false, 'inst-Bob-Bank': false });
    const reloaded = createSidebarExpansionStore(() => disk);
    expect(reloaded.get('alice')).toEqual({ 'owner-Bob': false, 'inst-Bob-Bank': false });
    expect(reloaded.get('bob')).toEqual({});
  });
  it('shares desktop and mobile expansion updates without overwriting other groups', () => {
    const store = createSidebarExpansionStore(storage);
    let notifications = 0;
    store.subscribe(() => { notifications += 1; });
    store.set('alice', previous => ({ ...previous, 'owner-Bob': false }));
    store.set('alice', previous => ({ ...previous, 'type-Bob-cash': false }));
    expect(store.get('alice')).toEqual({ 'owner-Bob': false, 'type-Bob-cash': false });
    expect(notifications).toBe(2);
  });
  it('ignores invalid stored data and works when browser storage is unavailable', () => {
    const disk = storage(); disk.setItem('famledger_sidebar_expansion:alice', 'invalid');
    expect(createSidebarExpansionStore(() => disk).get('alice')).toEqual({});
    const denied = createSidebarExpansionStore(() => { throw new Error('denied'); });
    denied.set('alice', { 'owner-Bob': false });
    expect(denied.get('alice')).toEqual({ 'owner-Bob': false });
  });
});
