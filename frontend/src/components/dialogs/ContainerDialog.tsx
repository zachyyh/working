import { useState } from 'react';
import { Dialog } from '../ui/Dialog';
import { FormField } from '../ui/FormField';
import { SelectField } from '../ui/SelectField';
import { isValidIp, isIpInCidr, getNextAvailableIp, getSubnetCapacity } from '../../utils/validation';
import type { Container } from '../../data/sampleTopology';
import { typeOptions, menuHierarchy, typeDisplayNames } from '../ContainerAspects';
import type { ContainerType } from '../ContainerAspects';

const typeLabel = Object.fromEntries(typeOptions.map(o => [o.value, o.label])) as Record<ContainerType, string>;

const statusOptions = [
  { value: 'running', label: 'Running' },
  { value: 'stopped', label: 'Stopped' },
  { value: 'paused', label: 'Paused' },
];

interface ContainerDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: {
    name: string;
    type: ContainerType;
    ip: string;
    image: string;
    status: 'running' | 'stopped' | 'paused';
    metadata: Record<string, string>;
    persistencePaths: string[];
  }) => void;
  initial?: Container;
  subnetCidr?: string;
  takenIps?: string[];
  existingNames?: string[];
}

function getNextName(existingNames: string[], base: string): string {
  const escaped = base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`^${escaped}\\s*(\\d+)$`, 'i');
  let max = 0;
  for (const n of existingNames) {
    const match = n.trim().match(pattern);
    if (match) max = Math.max(max, parseInt(match[1], 10));
  }
  return `${base} ${max + 1}`;
}

function ContainerDialogInner({ onClose, onSubmit, initial, subnetCidr, takenIps = [], existingNames }: Omit<ContainerDialogProps, 'open'>) {
  const defaultIp = initial?.ip ?? (subnetCidr ? getNextAvailableIp(subnetCidr, takenIps) ?? '' : '');
  const initialType: ContainerType = initial?.type ?? 'workstation';
  const defaultName = initial?.name ?? (existingNames ? getNextName(existingNames, typeLabel[initialType]) : '');

  const [name, setName] = useState(defaultName);
  const [nameIsAuto, setNameIsAuto] = useState(!initial);
  const [type, setType] = useState<ContainerType>(initialType);
  const [ip, setIp] = useState(defaultIp);
  const [ipError, setIpError] = useState('');
  const [image, setImage] = useState(initial?.image ?? '');
  const [status, setStatus] = useState<'running' | 'stopped' | 'paused'>(initial?.status ?? 'running');
  const [metaKey, setMetaKey] = useState('');
  const [metaValue, setMetaValue] = useState('');
  const [metadata, setMetadata] = useState<Record<string, string>>(initial?.metadata ? { ...initial.metadata } : {});
  const [persistencePathInput, setPersistencePathInput] = useState('');
  const [persistencePaths, setPersistencePaths] = useState<string[]>(initial?.persistencePaths ? [...initial.persistencePaths] : []);
  const [persistencePathError, setPersistencePathError] = useState('');

  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [activeTypeMenu, setActiveTypeMenu] = useState<string | null>(null);

const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    if (!isValidIp(ip)) {
      setIpError('Invalid IP address');
      return;
    }
    if (subnetCidr && !isIpInCidr(ip, subnetCidr)) {
      setIpError(`IP not in subnet ${subnetCidr}`);
      return;
    }
    // Check for duplicate (skip own IP when editing)
    const isOwnIp = initial && ip.trim() === initial.ip;
    if (!isOwnIp && takenIps.includes(ip.trim())) {
      setIpError('IP already in use');
      return;
    }

    // Extract the tag (the last word) if the user typed something like "postgres 1.0"
    const rawImage = image.trim();
    let extractedTag = rawImage ? rawImage.split(/\s+/).pop() || '' : '';

    // THE FIX: If the tag is still empty (user left it blank), auto-assign the default
    // tag from your menuHierarchy so the backend doesn't crash to Alpine.
    if (!extractedTag) {
      for (const category of Object.values(menuHierarchy)) {
        if (category[type] && category[type].length > 0) {
          extractedTag = category[type][0]; // Grabs the first valid tag (e.g., '1.0' or 'latest')
          break;
        }
      }
      // Absolute fallback just in case the menuHierarchy is missing the type
      if (!extractedTag) {
        extractedTag = 'latest';
      }
    }

    onSubmit({
      name: name.trim(),
      type,
      ip: ip.trim(),
      image: extractedTag,
      status,
      metadata,
      persistencePaths,
    });
    onClose();
  };

  const addMetaEntry = () => {
    if (metaKey.trim() && metaValue.trim()) {
      setMetadata(prev => ({ ...prev, [metaKey.trim()]: metaValue.trim() }));
      setMetaKey('');
      setMetaValue('');
    }
  };

  const removeMetaEntry = (key: string) => {
    setMetadata(prev => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const addPersistencePath = () => {
    const rawPath = persistencePathInput.trim();
    if (!rawPath) return;
    if (!rawPath.startsWith('/')) {
      setPersistencePathError('Path must be absolute (start with /)');
      return;
    }
    // Normalize the same way the backend does (posixpath.normpath equivalent)
    const parts = rawPath.split('/').filter(Boolean);
    const normalized = '/' + parts.join('/');
    if (normalized === '/') {
      setPersistencePathError('Cannot persist the root directory');
      return;
    }
    if (persistencePaths.includes(normalized)) {
      setPersistencePathError('Path already added');
      return;
    }
    setPersistencePathError('');
    setPersistencePaths(prev => [...prev, normalized]);
    setPersistencePathInput('');
  };

  const removePersistencePath = (path: string) => {
    setPersistencePaths(prev => prev.filter(p => p !== path));
  };

  return (
    <form onSubmit={handleSubmit}>
      <FormField label="Name" value={name} onChange={(v) => { setName(v); setNameIsAuto(false); }} placeholder="e.g. Core Router" />
<div 
        style={{ marginBottom: '16px', position: 'relative' }} 
      >
        <label style={{
          display: 'block',
          fontFamily: "var(--font-mono)",
          fontSize: '13px',
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '1px',
          marginBottom: '6px',
        }}>
          Template (Category ➔ Type ➔ Version)
        </label>
        
        <div
          onClick={() => setIsMenuOpen(!isMenuOpen)}
          style={{
            width: '100%',
            boxSizing: 'border-box',
            padding: '8px 12px',
            background: 'var(--bg-primary)',
            border: '1px solid var(--border-color)',
            borderRadius: '4px',
            color: type ? 'var(--text-primary)' : 'var(--text-dim)',
            fontFamily: "var(--font-mono)",
            fontSize: '15px',
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between'
          }}
        >
          {type && image ? `${typeDisplayNames[type]} (${image})` : type ? typeDisplayNames[type] : 'Select a template...'}
          <span style={{ fontSize: '10px' }}>▼</span>
        </div>

        {isMenuOpen && (
          <ul style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            width: '100%',
            background: 'var(--bg-primary)',
            border: '1px solid var(--border-color)',
            borderTop: 'none',
            borderRadius: '0 0 4px 4px',
            margin: 0,
            padding: 0,
            listStyle: 'none',
            zIndex: 100,
            fontFamily: "var(--font-mono)",
            fontSize: '14px',
            maxHeight: '250px',
            overflowY: 'auto'
          }}>
            {Object.keys(menuHierarchy).map((category) => (
              <li 
                key={category}
                style={{ position: 'relative' }}
              >
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
                  <span style={{ 
                    fontSize: '12px', 
                    transform: activeCategory === category ? 'rotate(90deg)' : 'rotate(0deg)',
                    transition: 'transform 0.15s ease'
                  }}>▶</span>
                </div>

                {/* Tier 2 - Inline Expanding Menu */}
                {activeCategory === category && (
                  <ul style={{
                    background: 'rgba(0,0,0,0.15)',
                    margin: 0,
                    padding: 0,
                    listStyle: 'none',
                    borderTop: '1px solid var(--border-color)',
                    borderBottom: '1px solid var(--border-color)'
                  }}>
                    {Object.keys(menuHierarchy[category]).map((t) => (
                      <li 
                        key={t}
                        style={{ position: 'relative' }}
                      >
                        <div 
                          onClick={(e) => {
                            e.stopPropagation();
                            setActiveTypeMenu(activeTypeMenu === t ? null : t);
                          }}
                          style={{
                            padding: '8px 12px 8px 24px',
                            color: activeTypeMenu === t ? 'var(--neon-cyan)' : 'var(--text-primary)',
                            background: activeTypeMenu === t ? 'rgba(0, 212, 255, 0.08)' : 'transparent',
                            cursor: 'pointer',
                            display: 'flex',
                            justifyContent: 'space-between'
                          }}
                        >
                          {typeDisplayNames[t]}
                          <span style={{ 
                            fontSize: '12px', 
                            transform: activeTypeMenu === t ? 'rotate(90deg)' : 'rotate(0deg)',
                            transition: 'transform 0.15s ease'
                          }}>▶</span>
                        </div>

                        {activeTypeMenu === t && (
                          <ul style={{
                            background: 'rgba(0,0,0,0.25)',
                            margin: 0,
                            padding: 0,
                            listStyle: 'none',
                            borderTop: '1px solid var(--border-color)'
                          }}>
                            {menuHierarchy[category][t as ContainerType]?.map((tag) => (
                              <li 
                                key={tag}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  const selectedType = t as ContainerType;
                                  setType(selectedType);
                                  setImage(tag); 
                                  setIsMenuOpen(false);
                                  
                                  if (nameIsAuto && existingNames) {
                                    setName(getNextName(existingNames, typeLabel[selectedType]));
                                  }
                                }}
                                style={{
                                  padding: '8px 12px 8px 36px',
                                  color: 'var(--text-primary)',
                                  cursor: 'pointer',
                                  borderBottom: '1px solid rgba(255,255,255,0.05)'
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.color = 'var(--neon-green)';
                                  e.currentTarget.style.background = 'rgba(0, 255, 159, 0.08)';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.color = 'var(--text-primary)';
                                  e.currentTarget.style.background = 'transparent';
                                }}
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
      <FormField
        label="IP Address"
        value={ip}
        onChange={(v) => { setIp(v); setIpError(''); }}
        placeholder="e.g. 10.0.1.1"
        error={ipError}
      />
      {subnetCidr && (() => {
        const cap = getSubnetCapacity(subnetCidr);
        const used = takenIps.length;
        const avail = Math.max(0, cap - used);
        return (
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '15px',
            color: avail === 0 ? 'var(--neon-red)' : 'var(--text-dim)',
            marginTop: '-8px',
            marginBottom: '12px',
          }}>
            {avail === 0 ? 'Subnet full — ' : ''}{used}/{cap} IPs used in {subnetCidr}
          </div>
        );
      })()}
      <FormField label="Image" value={image} onChange={setImage} placeholder="e.g. ubuntu:22.04 (optional)" />
      <SelectField label="Status" value={status} onChange={(v) => setStatus(v as 'running' | 'stopped' | 'paused')} options={statusOptions} />

      {/* Metadata */}
      <div style={{ marginBottom: '16px' }}>
        <label style={{
          display: 'block',
          fontFamily: "var(--font-mono)",
          fontSize: '13px',
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '1px',
          marginBottom: '6px',
        }}>
          Metadata
        </label>
        {Object.entries(metadata).map(([k, v]) => (
          <div key={k} style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            marginBottom: '4px',
            fontFamily: "var(--font-mono)",
            fontSize: '15px',
            color: 'var(--text-primary)',
            minWidth: 0,
          }}>
            <span style={{ color: 'var(--neon-cyan)', flexShrink: 0 }}>{k}</span>
            <span style={{ color: 'var(--text-dim)', flexShrink: 0 }}>=</span>
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v}</span>
            <button
              type="button"
              onClick={() => removeMetaEntry(k)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--neon-red)',
                cursor: 'pointer',
                fontFamily: "var(--font-mono)",
                fontSize: '15px',
                padding: '0 4px',
                flexShrink: 0,
              }}
            >
              x
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
          <input
            value={metaKey}
            onChange={(e) => setMetaKey(e.target.value)}
            placeholder="key"
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '6px 8px',
              background: 'var(--bg-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: '4px',
              color: 'var(--text-primary)',
              fontFamily: "var(--font-mono)",
              fontSize: '15px',
              outline: 'none',
            }}
          />
          <input
            value={metaValue}
            onChange={(e) => setMetaValue(e.target.value)}
            placeholder="value"
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '6px 8px',
              background: 'var(--bg-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: '4px',
              color: 'var(--text-primary)',
              fontFamily: "var(--font-mono)",
              fontSize: '15px',
              outline: 'none',
            }}
          />
          <button
            type="button"
            onClick={addMetaEntry}
            style={{
              width: '100%',
              padding: '6px 10px',
              background: 'rgba(0, 212, 255, 0.08)',
              border: '1px solid var(--neon-cyan)',
              borderRadius: '4px',
              color: 'var(--neon-cyan)',
              fontFamily: "var(--font-mono)",
              fontSize: '15px',
              cursor: 'pointer',
            }}
          >
            + Add
          </button>
        </div>
      </div>

      {/* Persistence Paths */}
      <div style={{ marginBottom: '16px' }}>
        <label style={{
          display: 'block',
          fontFamily: "var(--font-mono)",
          fontSize: '10px',
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '1px',
          marginBottom: '6px',
        }}>
          Persistent Paths
        </label>
        <div style={{
          fontFamily: "var(--font-mono)",
          fontSize: '11px',
          color: 'var(--text-dim)',
          marginBottom: '8px',
        }}>
          Absolute in-container directories to keep across destroy/deploy.
        </div>
        {persistencePaths.map((path) => (
          <div key={path} style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            marginBottom: '4px',
            fontFamily: "var(--font-mono)",
            fontSize: '12px',
            color: 'var(--text-primary)',
          }}>
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {path}
            </span>
            <button
              type="button"
              onClick={() => removePersistencePath(path)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--neon-red)',
                cursor: 'pointer',
                fontFamily: "var(--font-mono)",
                fontSize: '12px',
                padding: '0 4px',
                flexShrink: 0,
              }}
            >
              x
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
          <input
            value={persistencePathInput}
            onChange={(e) => {
              setPersistencePathInput(e.target.value);
              setPersistencePathError('');
            }}
            placeholder="/var/lib/app"
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '6px 8px',
              background: 'var(--bg-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: '4px',
              color: 'var(--text-primary)',
              fontFamily: "var(--font-mono)",
              fontSize: '12px',
              outline: 'none',
            }}
          />
          {persistencePathError && (
            <div style={{
              fontFamily: "var(--font-mono)",
              fontSize: '11px',
              color: 'var(--neon-red)',
            }}>
              {persistencePathError}
            </div>
          )}
          <button
            type="button"
            onClick={addPersistencePath}
            style={{
              width: '100%',
              padding: '6px 10px',
              background: 'rgba(0, 255, 159, 0.08)',
              border: '1px solid var(--neon-green)',
              borderRadius: '4px',
              color: 'var(--neon-green)',
              fontFamily: "var(--font-mono)",
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            + Add Path
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '8px' }}>
        <button
          type="button"
          onClick={onClose}
          style={{
            padding: '10px 20px',
            background: 'none',
            border: '1px solid var(--border-color)',
            borderRadius: '4px',
            color: 'var(--text-secondary)',
            fontFamily: "var(--font-mono)",
            fontSize: '15px',
            cursor: 'pointer',
          }}
        >
          Cancel
        </button>
        <button
          type="submit"
          style={{
            padding: '10px 20px',
            background: 'rgba(0, 255, 159, 0.08)',
            border: '1px solid var(--neon-green)',
            borderRadius: '4px',
            color: 'var(--neon-green)',
            fontFamily: "var(--font-mono)",
            fontSize: '15px',
            cursor: 'pointer',
          }}
        >
          {initial ? 'Save' : 'Add Container'}
        </button>
      </div>
    </form>
  );
}

export function ContainerDialog({ open, onClose, onSubmit, initial, subnetCidr, takenIps, existingNames }: ContainerDialogProps) {
  return (
    <Dialog title={initial ? 'Edit Container' : 'Add Container'} open={open} onClose={onClose} width={460}>
      {open && <ContainerDialogInner onClose={onClose} onSubmit={onSubmit} initial={initial} subnetCidr={subnetCidr} takenIps={takenIps} existingNames={existingNames} />}
    </Dialog>
  );
}
