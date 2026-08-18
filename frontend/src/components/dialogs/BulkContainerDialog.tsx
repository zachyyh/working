import { useState, useCallback, useMemo } from 'react';
import { Dialog } from '../ui/Dialog';
import { FormField } from '../ui/FormField';
import { isValidIp, isIpInCidr, getAvailableIps, getSubnetCapacity } from '../../utils/validation';
import { typeOptions, menuHierarchy, typeDisplayNames } from '../ContainerAspects';
import type { ContainerType } from '../ContainerAspects';

const typeLabel = Object.fromEntries(typeOptions.map(o => [o.value, o.label])) as Record<ContainerType, string>;

interface BulkEntry {
  key: number;
  name: string;
  type: ContainerType;
  image: string;
  ip: string;
}

interface BulkContainerDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (entries: { name: string; type: ContainerType; image: string; ip: string }[]) => void;
  subnetCidr: string;
  takenIps: string[];
  existingNames?: string[];
}

let nextKey = 0;

function BulkContainerDialogInner({ onClose, onSubmit, subnetCidr, takenIps, existingNames = [] }: Omit<BulkContainerDialogProps, 'open'>) {
  // Generator fields
  const [prefix, setPrefix] = useState(typeLabel['workstation']);
  const [prefixIsAuto, setPrefixIsAuto] = useState(true);
  const [genType, setGenType] = useState<ContainerType>('workstation');
  const [genImage, setGenImage] = useState<string>('');
  const [count, setCount] = useState('5');
  const [genError, setGenError] = useState('');

  // Table entries
  const [entries, setEntries] = useState<BulkEntry[]>([]);

  // Menu states for inline flyouts
  const [activeMenu, setActiveMenu] = useState<'gen' | number | null>(null);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [activeTypeMenu, setActiveTypeMenu] = useState<string | null>(null);

  // Subnet capacity
  const totalCapacity = useMemo(() => getSubnetCapacity(subnetCidr), [subnetCidr]);
  const pendingCount = useMemo(
    () => entries.filter(e => isValidIp(e.ip)).length,
    [entries]
  );
  const usedCount = takenIps.length;
  const availableCount = Math.max(0, totalCapacity - usedCount - pendingCount);

  const handleGenerate = useCallback(() => {
    const n = parseInt(count, 10);
    if (isNaN(n) || n < 1 || n > 500) {
      setGenError('Count must be 1–500');
      return;
    }

    const currentTaken = [...takenIps, ...entries.map(e => e.ip).filter(ip => isValidIp(ip))];
    const ips = getAvailableIps(subnetCidr, currentTaken, n);
    if (ips.length === 0) {
      setGenError('No available IPs in subnet');
      return;
    }
    if (ips.length < n) {
      setGenError(`Only ${ips.length} IPs available (requested ${n})`);
    } else {
      setGenError('');
    }
    const escaped = prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`^${escaped}\\s*(\\d+)$`, 'i');
    let max = 0;
    for (const name of [...existingNames, ...entries.map(e => e.name)]) {
      const match = name.trim().match(pattern);
      if (match) max = Math.max(max, parseInt(match[1], 10));
    }

    const generated: BulkEntry[] = ips.map((ip, i) => ({
      key: nextKey++,
      name: `${prefix} ${max + i + 1}`,
      type: genType,
      image: genImage,
      ip,
    }));
    setEntries(prev => [...prev, ...generated]);
  }, [prefix, genType, genImage, count, subnetCidr, takenIps, entries, existingNames]);

  const handleAddRow = useCallback(() => {
    setEntries(prev => [...prev, { key: nextKey++, name: '', type: 'workstation', image: '', ip: '' }]);
  }, []);

  const updateEntry = useCallback((key: number, field: keyof BulkEntry, value: string) => {
    setEntries(prev => prev.map(e =>
      e.key === key ? { ...e, [field]: value } : e
    ));
  }, []);

  const removeEntry = useCallback((key: number) => {
    setEntries(prev => prev.filter(e => e.key !== key));
  }, []);

  const clearAll = useCallback(() => setEntries([]), []);

  const isEntryValid = useCallback((entry: BulkEntry) => {
    if (!entry.name.trim() || !isValidIp(entry.ip)) return false;
    if (!isIpInCidr(entry.ip, subnetCidr)) return false;
    if (takenIps.includes(entry.ip.trim())) return false;
    const firstWithIp = entries.find(e => e.ip.trim() === entry.ip.trim());
    if (firstWithIp && firstWithIp.key !== entry.key) return false;
    return true;
  }, [subnetCidr, takenIps, entries]);

  const getIpError = useCallback((entry: BulkEntry): string => {
    if (!entry.ip) return '';
    if (!isValidIp(entry.ip)) return 'Invalid IP';
    if (!isIpInCidr(entry.ip, subnetCidr)) return 'Outside subnet';
    if (takenIps.includes(entry.ip.trim())) return 'Already taken';
    const dupes = entries.filter(e => e.key !== entry.key && e.ip.trim() === entry.ip.trim());
    if (dupes.length > 0) return 'Duplicate';
    return '';
  }, [subnetCidr, takenIps, entries]);

const handleSubmit = () => {
    const valid = entries.filter(isEntryValid);
    if (valid.length === 0) return;
    
    const seen = new Set<string>();
    const deduped = valid.filter(e => {
      const ip = e.ip.trim();
      if (seen.has(ip)) return false;
      seen.add(ip);
      return true;
    });
    
    if (deduped.length === 0) return;

    // Format the image string and apply defaults for every row
    const finalEntries = deduped.map(e => {
      // 1. Extract the tag if somehow there is a string with spaces
      let extractedTag = e.image.trim() ? e.image.trim().split(/\s+/).pop() || '' : '';

      // 2. If the tag is empty (user didn't open the menu for this row/generator),
      // auto-assign the default tag from menuHierarchy based on the row's type.
      if (!extractedTag) {
        for (const category of Object.values(menuHierarchy)) {
          // @ts-expect-error - category indexing is safe here based on how menuHierarchy is built
          if (category[e.type] && category[e.type].length > 0) {
            // @ts-expect-error
            extractedTag = category[e.type][0]; 
            break;
          }
        }
        // Absolute fallback
        if (!extractedTag) {
          extractedTag = 'latest';
        }
      }

      // Return the cleaned up row
      return { 
        name: e.name.trim(), 
        type: e.type, 
        image: extractedTag, 
        ip: e.ip.trim() 
      };
    });

    onSubmit(finalEntries);
    onClose();
  };

  const validCount = entries.filter(isEntryValid).length;

  const inputStyle: React.CSSProperties = {
    padding: '4px 6px',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border-color)',
    borderRadius: '3px',
    color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    outline: 'none',
    width: '100%',
  };

  return (
    <div>
      {/* Generator section */}
      <div style={{
        padding: '12px',
        background: 'rgba(0, 255, 159, 0.03)',
        border: '1px solid rgba(0, 255, 159, 0.15)',
        borderRadius: '6px',
        marginBottom: '16px',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '10px',
        }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
            color: 'var(--neon-green)',
            textTransform: 'uppercase',
            letterSpacing: '1px',
          }}>
            Quick Generate
          </div>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
            color: 'var(--text-dim)',
            textAlign: 'right',
          }}>
            <div>{subnetCidr}</div>
            <div style={{ color: availableCount === 0 ? 'var(--neon-red)' : 'var(--text-dim)' }}>
              {usedCount + pendingCount}/{totalCapacity} used — {availableCount} available
            </div>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 0.5fr', gap: '8px', alignItems: 'end' }}>
          <FormField label="Name prefix" value={prefix} onChange={v => { setPrefix(v); setPrefixIsAuto(false); }} placeholder="e.g. Server" />
          
          <div style={{ position: 'relative', paddingBottom: '16px' }}>
            <label style={{
              display: 'block',
              fontFamily: "var(--font-mono)",
              fontSize: '13px',
              color: 'var(--text-dim)',
              textTransform: 'uppercase',
              letterSpacing: '1px',
              marginBottom: '6px',
            }}>
              Template
            </label>
            <div
              onClick={() => setActiveMenu(activeMenu === 'gen' ? null : 'gen')}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '8px 12px',
                background: 'var(--bg-primary)',
                border: '1px solid var(--border-color)',
                borderRadius: '4px',
                color: genType ? 'var(--text-primary)' : 'var(--text-dim)',
                fontFamily: "var(--font-mono)",
                fontSize: '13px',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {genType && genImage ? `${typeDisplayNames[genType]} (${genImage})` : genType ? typeDisplayNames[genType] : 'Select...'}
              </span>
              <span style={{ fontSize: '10px', marginLeft: '6px' }}>▼</span>
            </div>

            {activeMenu === 'gen' && (
              <ul style={{
                position: 'absolute',
                top: 'calc(100% - 16px)',
                left: 0,
                width: '100%',
                minWidth: '220px',
                background: 'var(--bg-primary)',
                border: '1px solid var(--border-color)',
                borderRadius: '0 0 4px 4px',
                margin: 0,
                padding: 0,
                listStyle: 'none',
                zIndex: 100,
                fontFamily: "var(--font-mono)",
                fontSize: '13px',
                maxHeight: '250px',
                overflowY: 'auto'
              }}>
                {Object.keys(menuHierarchy).map((category) => (
                  <li key={category} style={{ position: 'relative' }}>
                    <div 
                      onClick={(e) => {
                        e.stopPropagation();
                        if (activeCategory === category) {
                          setActiveCategory(null);
                          setActiveTypeMenu(null);
                        } else {
                          setActiveCategory(category);
                          setActiveTypeMenu(null);
                        }
                      }}
                      style={{
                        padding: '8px 12px',
                        color: activeCategory === category ? 'var(--neon-cyan)' : 'var(--text-primary)',
                        background: activeCategory === category ? 'rgba(0, 212, 255, 0.08)' : 'transparent',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        textTransform: 'capitalize' 
                      }}
                    >
                      {category}
                      <span style={{ fontSize: '12px', transform: activeCategory === category ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
                    </div>

                    {activeCategory === category && (
                      <ul style={{ background: 'rgba(0,0,0,0.15)', margin: 0, padding: 0, listStyle: 'none', borderTop: '1px solid var(--border-color)' }}>
                        {Object.keys(menuHierarchy[category]).map((t) => (
                          <li key={t} style={{ position: 'relative' }}>
                            <div 
                              onClick={(e) => {
                                e.stopPropagation();
                                setActiveTypeMenu(activeTypeMenu === t ? null : t);
                              }}
                              style={{ padding: '8px 12px 8px 24px', color: activeTypeMenu === t ? 'var(--neon-cyan)' : 'var(--text-primary)', cursor: 'pointer', display: 'flex', justifyContent: 'space-between' }}
                            >
                              {typeDisplayNames[t as ContainerType]}
                              <span style={{ fontSize: '12px', transform: activeTypeMenu === t ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
                            </div>

                            {activeTypeMenu === t && (
                              <ul style={{ background: 'rgba(0,0,0,0.25)', margin: 0, padding: 0, listStyle: 'none', borderTop: '1px solid var(--border-color)' }}>
                                {menuHierarchy[category][t as ContainerType]?.map((tag) => (
                                  <li 
                                    key={tag}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      const selectedType = t as ContainerType;
                                      setGenType(selectedType);
                                      setGenImage(tag); 
                                      setActiveMenu(null);
                                      if (prefixIsAuto) setPrefix(typeLabel[selectedType]);
                                    }}
                                    style={{ padding: '8px 12px 8px 36px', color: 'var(--text-primary)', cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.05)' }}
                                    onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--neon-green)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-primary)'; }}
                                  >
                                    {tag}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div style={{ paddingBottom: '16px' }}>
            <FormField label="Count" value={count} onChange={v => { setCount(v); setGenError(''); }} placeholder="1–500" type="number" />
          </div>
        </div>
        {genError && (
          <div style={{ color: 'var(--neon-red)', fontFamily: 'var(--font-mono)', fontSize: '13px', marginTop: '6px' }}>
            {genError}
          </div>
        )}
        <button
          type="button"
          onClick={handleGenerate}
          disabled={availableCount === 0}
          style={{
            marginTop: '10px',
            padding: '6px 14px',
            background: availableCount > 0 ? 'rgba(0, 255, 159, 0.08)' : 'transparent',
            border: `1px solid ${availableCount > 0 ? 'var(--neon-green)' : 'var(--border-color)'}`,
            borderRadius: '4px',
            color: availableCount > 0 ? 'var(--neon-green)' : 'var(--text-dim)',
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            cursor: availableCount > 0 ? 'pointer' : 'default',
            opacity: availableCount > 0 ? 1 : 0.5,
          }}
        >
          {availableCount === 0 ? 'Subnet full' : `Generate ${count && !isNaN(Number(count)) ? `(${count})` : ''}`}
        </button>
      </div>

      {/* Entries table */}
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
        color: 'var(--text-dim)',
        textTransform: 'uppercase',
        letterSpacing: '1px',
        marginBottom: '6px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <span>Entries ({entries.length})</span>
        <div style={{ display: 'flex', gap: '8px' }}>
          {entries.length > 0 && (
            <button
              type="button"
              onClick={clearAll}
              style={{ background: 'none', border: 'none', color: 'var(--neon-red)', fontFamily: 'var(--font-mono)', fontSize: '12px', cursor: 'pointer', textTransform: 'uppercase' }}
            >
              Clear all
            </button>
          )}
          <button
            type="button"
            onClick={handleAddRow}
            style={{ background: 'none', border: 'none', color: 'var(--neon-cyan)', fontFamily: 'var(--font-mono)', fontSize: '12px', cursor: 'pointer', textTransform: 'uppercase' }}
          >
            + Add row
          </button>
        </div>
      </div>

      {entries.length > 0 ? (
        <div style={{
          maxHeight: '320px',
          overflowY: 'auto',
          border: '1px solid var(--border-color)',
          borderRadius: '4px',
          paddingBottom: '80px', // Extra space so bottom flyouts don't get clipped by the container
        }}>
          {/* Table header */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1.5fr 2fr 1.5fr 28px',
            gap: '6px',
            padding: '6px 8px',
            background: 'rgba(0, 212, 255, 0.05)',
            borderBottom: '1px solid var(--border-color)',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--text-dim)',
            textTransform: 'uppercase',
            letterSpacing: '1px',
            position: 'sticky',
            top: 0,
            zIndex: 10,
          }}>
            <span>Name</span>
            <span>Template</span>
            <span>IP</span>
            <span />
          </div>

          {/* Table rows */}
          {entries.map((entry) => (
            <div
              key={entry.key}
              style={{
                display: 'grid',
                gridTemplateColumns: '1.5fr 2fr 1.5fr 28px',
                gap: '6px',
                padding: '4px 8px',
                alignItems: 'center',
                borderBottom: '1px solid rgba(255,255,255,0.03)',
              }}
            >
              <input
                value={entry.name}
                onChange={e => updateEntry(entry.key, 'name', e.target.value)}
                style={{ ...inputStyle, borderColor: !entry.name.trim() ? 'var(--neon-red)' : 'var(--border-color)' }}
                placeholder="Name"
              />

              {/* Inline template flyout for the row */}
              <div style={{ position: 'relative', width: '100%' }}>
                <div
                  onClick={() => setActiveMenu(activeMenu === entry.key ? null : entry.key)}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '4px 6px',
                    background: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '3px',
                    color: entry.type ? 'var(--text-primary)' : 'var(--text-dim)',
                    fontFamily: "var(--font-mono)",
                    fontSize: '13px',
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {entry.type && entry.image ? `${typeDisplayNames[entry.type]} (${entry.image})` : entry.type ? typeDisplayNames[entry.type] : 'Select...'}
                  </span>
                  <span style={{ fontSize: '10px', marginLeft: '6px' }}>▼</span>
                </div>

                {activeMenu === entry.key && (
                  <ul style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    width: '100%',
                    minWidth: '220px',
                    background: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    borderTop: 'none',
                    borderRadius: '0 0 4px 4px',
                    margin: 0,
                    padding: 0,
                    listStyle: 'none',
                    zIndex: 100,
                    fontFamily: "var(--font-mono)",
                    fontSize: '13px',
                    maxHeight: '250px',
                    overflowY: 'auto',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.5)'
                  }}>
                    {Object.keys(menuHierarchy).map((category) => (
                      <li key={category} style={{ position: 'relative' }}>
                        <div 
                          onClick={(e) => {
                            e.stopPropagation();
                            if (activeCategory === category) {
                              setActiveCategory(null);
                              setActiveTypeMenu(null);
                            } else {
                              setActiveCategory(category);
                              setActiveTypeMenu(null);
                            }
                          }}
                          style={{
                            padding: '8px 12px',
                            color: activeCategory === category ? 'var(--neon-cyan)' : 'var(--text-primary)',
                            background: activeCategory === category ? 'rgba(0, 212, 255, 0.08)' : 'transparent',
                            cursor: 'pointer',
                            display: 'flex',
                            justifyContent: 'space-between',
                            textTransform: 'capitalize' 
                          }}
                        >
                          {category}
                          <span style={{ fontSize: '12px', transform: activeCategory === category ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
                        </div>

                        {activeCategory === category && (
                          <ul style={{ background: 'rgba(0,0,0,0.15)', margin: 0, padding: 0, listStyle: 'none', borderTop: '1px solid var(--border-color)' }}>
                            {Object.keys(menuHierarchy[category]).map((t) => (
                              <li key={t} style={{ position: 'relative' }}>
                                <div 
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setActiveTypeMenu(activeTypeMenu === t ? null : t);
                                  }}
                                  style={{ padding: '8px 12px 8px 24px', color: activeTypeMenu === t ? 'var(--neon-cyan)' : 'var(--text-primary)', cursor: 'pointer', display: 'flex', justifyContent: 'space-between' }}
                                >
                                  {typeDisplayNames[t as ContainerType]}
                                  <span style={{ fontSize: '12px', transform: activeTypeMenu === t ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
                                </div>

                                {activeTypeMenu === t && (
                                  <ul style={{ background: 'rgba(0,0,0,0.25)', margin: 0, padding: 0, listStyle: 'none', borderTop: '1px solid var(--border-color)' }}>
                                    {menuHierarchy[category][t as ContainerType]?.map((tag) => (
                                      <li 
                                        key={tag}
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          const selectedType = t as ContainerType;
                                          updateEntry(entry.key, 'type', selectedType);
                                          updateEntry(entry.key, 'image', tag);
                                          setActiveMenu(null);
                                        }}
                                        style={{ padding: '8px 12px 8px 36px', color: 'var(--text-primary)', cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.05)' }}
                                        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--neon-green)'; }}
                                        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-primary)'; }}
                                      >
                                        {tag}
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <input
                value={entry.ip}
                onChange={e => updateEntry(entry.key, 'ip', e.target.value)}
                title={getIpError(entry) || undefined}
                style={{ ...inputStyle, borderColor: getIpError(entry) ? 'var(--neon-red)' : 'var(--border-color)' }}
                placeholder="IP"
              />
              <button
                type="button"
                onClick={() => removeEntry(entry.key)}
                style={{ background: 'none', border: 'none', color: 'var(--neon-red)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '13px', padding: '0', lineHeight: 1 }}
              >
                x
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div style={{
          padding: '24px',
          textAlign: 'center',
          fontFamily: 'var(--font-mono)',
          fontSize: '13px',
          color: 'var(--text-dim)',
          border: '1px dashed var(--border-color)',
          borderRadius: '4px',
        }}>
          No entries yet. Use Generate or Add Row above.
        </div>
      )}

      {/* Footer */}
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '16px' }}>
        <button
          type="button"
          onClick={onClose}
          style={{ padding: '8px 16px', background: 'none', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '13px', cursor: 'pointer' }}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={validCount === 0}
          style={{
            padding: '8px 16px',
            background: validCount > 0 ? 'rgba(0, 255, 159, 0.08)' : 'transparent',
            border: `1px solid ${validCount > 0 ? 'var(--neon-green)' : 'var(--border-color)'}`,
            borderRadius: '4px',
            color: validCount > 0 ? 'var(--neon-green)' : 'var(--text-dim)',
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            cursor: validCount > 0 ? 'pointer' : 'default',
            opacity: validCount > 0 ? 1 : 0.5,
          }}
        >
          Add {validCount > 0 ? `${validCount} Container${validCount > 1 ? 's' : ''}` : 'Containers'}
        </button>
      </div>
    </div>
  );
}

export function BulkContainerDialog({ open, onClose, onSubmit, subnetCidr, takenIps, existingNames }: BulkContainerDialogProps) {
  return (
    <Dialog title="Bulk Add Containers" open={open} onClose={onClose} width={720}>
      {open && <BulkContainerDialogInner onClose={onClose} onSubmit={onSubmit} subnetCidr={subnetCidr} takenIps={takenIps} existingNames={existingNames} />}
    </Dialog>
  );
}