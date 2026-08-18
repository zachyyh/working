import { useContext, useEffect, useState } from 'react';
import type { Container } from '../data/sampleTopology';
import { TopologyDispatchContext } from '../store/TopologyContext';
import { AuthContext } from '../store/AuthContext';
import { ContainerDialog } from './dialogs/ContainerDialog';
import { ConfirmDialog } from './dialogs/ConfirmDialog';
import { ContainerConfigDialog } from './dialogs/ContainerConfigDialog';
import { prewarmCapture } from '../api/client';
import { typeDisplayNames } from './ContainerAspects';
import type { ContainerType } from './ContainerAspects';

interface NodeInfoPanelProps {
  container: Container | null;
  onClose: () => void;
  onOpenTerminal: (container: Container) => void;
  onOpenWireshark?: (container: Container) => void;
  siteId: string | null;
  subnetId: string | null;
  topologyId: string | null;
  readOnly?: boolean;
  deployStatus?: string;
}

function isHmiContainer(container: Container): boolean {
  return container.type === 'hmi' || (container.type === 'workstation' && /hmi/i.test(container.name));
}

function webUiPort(container: Container): number {
  const raw = container.metadata?.webUiPort;
  const parsed = raw ? Number(raw) : NaN;
  if (Number.isInteger(parsed) && parsed >= 1 && parsed <= 65535) return parsed;
  if (container.type === 'plc' || isHmiContainer(container)) return 8080;
  return 80;
}

export function NodeInfoPanel({
  container,
  onClose,
  onOpenTerminal,
  onOpenWireshark,
  siteId,
  subnetId,
  topologyId,
  readOnly,
  deployStatus,
}: NodeInfoPanelProps) {
  const dispatch = useContext(TopologyDispatchContext);
  const auth = useContext(AuthContext);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);

  // Pre-warm the Wireshark sidecar as soon as a deployed container is selected,
  // so it's ready by the time the user clicks "Capture Traffic".
  useEffect(() => {
    if (!container || !topologyId || deployStatus !== 'deployed' || !onOpenWireshark) return;
    prewarmCapture(topologyId, container.id).catch(() => {/* best-effort */});
  }, [container?.id, topologyId, deployStatus]);

  const handleEdit = (data: {
    name: string; type: ContainerType; ip: string; image: string;
    status: 'running' | 'stopped' | 'paused'; metadata: Record<string, string>;
    persistencePaths: string[];
  }) => {
    if (!container || !siteId || !subnetId) return;
    dispatch({
      type: 'UPDATE_CONTAINER',
      payload: {
        siteId,
        subnetId,
        containerId: container.id,
        updates: {
          name: data.name,
          type: data.type,
          ip: data.ip,
          image: data.image || undefined,
          status: data.status,
          metadata: Object.keys(data.metadata).length > 0 ? data.metadata : undefined,
          persistencePaths: data.persistencePaths.length > 0 ? data.persistencePaths : undefined,
        },
      },
    });
  };

  const handleDelete = () => {
    if (!container || !siteId || !subnetId) return;
    dispatch({
      type: 'DELETE_CONTAINER',
      payload: { siteId, subnetId, containerId: container.id },
    });
    setDeleteOpen(false);
    onClose();
  };

  const handleConfigSave = (configData: Record<string, any>) => {
    if (!container || !siteId || !subnetId) return;
    dispatch({
      type: 'UPDATE_CONTAINER',
      payload: {
        siteId,
        subnetId,
        containerId: container.id,
        updates: { config: configData }, // Automatically merges into the container!
      },
    });
  };

  return (
    <div className={`info-panel ${container ? 'open' : ''}`}>
      {container && (
        <>
          <div className="info-panel-header">
            <div className="info-panel-title">NODE INFO</div>
            <button className="info-panel-close" onClick={onClose}>
              x
            </button>
          </div>

          <div className="info-panel-body">
            <div className="info-field">
              <div className="info-label">Name</div>
              <div className="info-value">{container.name}</div>
            </div>

            <div className="info-field">
              <div className="info-label">Type</div>
              <div className="info-value">
                {typeDisplayNames[container.type] || container.type}
              </div>
            </div>

            <div className="info-field">
              <div className="info-label">IP Address</div>
              <div className="info-value">{container.ip}</div>
            </div>

            {container.image && (
              <div className="info-field">
                <div className="info-label">Image</div>
                <div className="info-value">{container.image}</div>
              </div>
            )}

            {container.status && (
              <div className="info-field">
                <div className="info-label">Status</div>
                <div
                  className={`info-value status-${container.status}`}
                >
                  {container.status.toUpperCase()}
                </div>
              </div>
            )}

            {container.metadata && Object.keys(container.metadata).length > 0 && (
              <>
                <div
                  style={{
                    height: '1px',
                    background: '#1e1e2e',
                    margin: '16px 0',
                  }}
                />
                <div className="info-field">
                  <div className="info-label">Metadata</div>
                </div>
                {Object.entries(container.metadata).map(([key, value]) => (
                  <div className="info-field" key={key}>
                    <div className="info-label">{key}</div>
                    <div className="info-value">{value}</div>
                  </div>
                ))}
              </>
            )}

            {container.persistencePaths && container.persistencePaths.length > 0 && (
              <>
                <div
                  style={{
                    height: '1px',
                    background: '#1e1e2e',
                    margin: '16px 0',
                  }}
                />
                <div className="info-field">
                  <div className="info-label">Persistence Paths</div>
                </div>
                {container.persistencePaths.map((path) => (
                  <div className="info-field" key={path}>
                    <div className="info-value">{path}</div>
                  </div>
                ))}
              </>
            )}
            
            {/* Displaying Current Config in the Panel (Optional but helpful) */}
            {container.config && Object.keys(container.config).length > 0 && (
              <>
                <div style={{ height: '1px', background: '#1e1e2e', margin: '16px 0' }} />
                <div className="info-field">
                  <div className="info-label">Configuration</div>
                </div>
                {Object.entries(container.config).map(([key, value]) => (
                  <div className="info-field" key={key}>
                    <div className="info-label">{key}</div>
                    <div className="info-value">{String(value)}</div>
                  </div>
                ))}
              </>
            )}
          </div>

          <div className="info-panel-actions">
            <button
              className="btn-terminal"
              onClick={() => onOpenTerminal(container)}
            >
              Open Terminal
            </button>
            {onOpenWireshark && deployStatus === 'deployed' && (
              <button
                className="btn-terminal"
                style={{ marginTop: '8px', background: 'rgba(180, 77, 255, 0.1)', borderColor: 'var(--neon-purple, #b44dff)', color: 'var(--neon-purple, #b44dff)' }}
                onClick={() => onOpenWireshark(container)}
              >
                Capture Traffic
              </button>
            )}
            {(container.type === 'web-server' || container.type === 'plc' || container.type === 'hmi' || isHmiContainer(container)) && auth?.token && topologyId && (
              <button
                className="btn-terminal"
                style={{ marginTop: '8px', background: 'rgba(0, 255, 159, 0.1)', borderColor: 'var(--neon-green)', color: 'var(--neon-green)' }}
                onClick={() => {
                  const base = `${window.location.origin}/api/proxy/${topologyId}/${container.id}`;
                  const hmiPath = (container.type === 'hmi' || isHmiContainer(container)) ? '/ScadaBR' : '/';
                  const url = `${base}${hmiPath}?token=${auth.token}&port=${webUiPort(container)}`;
                  window.open(url, '_blank');
                }}
              >
                🌐 Open Web UI
              </button>
            )}
            {!readOnly && (
              <>
                {/* <-- ADDED CONFIGURE BUTTON HERE --> */}
                <button
                  onClick={() => setConfigOpen(true)}
                  style={{
                    width: '100%',
                    marginTop: '16px',
                    padding: '12px 18px',
                    background: 'rgba(255, 193, 7, 0.08)',
                    border: '1px solid var(--neon-yellow, #ffc107)',
                    color: 'var(--neon-yellow, #ffc107)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '16px',
                    cursor: 'pointer',
                    borderRadius: '4px',
                    textTransform: 'uppercase',
                    letterSpacing: '1px',
                  }}
                >
                  ⚙️ Configure Node
                </button>
                <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                  <button
                    onClick={() => setEditOpen(true)}
                    style={{
                      flex: 1,
                      padding: '12px 18px',
                      background: 'rgba(0, 212, 255, 0.08)',
                      border: '1px solid var(--neon-cyan)',
                      color: 'var(--neon-cyan)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '16px',
                      cursor: 'pointer',
                      borderRadius: '4px',
                      textTransform: 'uppercase',
                      letterSpacing: '1px',
                    }}
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => setDeleteOpen(true)}
                    style={{
                      flex: 1,
                      padding: '12px 18px',
                      background: 'rgba(255, 51, 68, 0.08)',
                      border: '1px solid var(--neon-red)',
                      color: 'var(--neon-red)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '16px',
                      cursor: 'pointer',
                      borderRadius: '4px',
                      textTransform: 'uppercase',
                      letterSpacing: '1px',
                    }}
                  >
                    Delete
                  </button>
                </div>
              </>
            )}
          </div>

          {!readOnly && (
            <>
              <ContainerDialog
                open={editOpen}
                onClose={() => setEditOpen(false)}
                onSubmit={handleEdit}
                initial={container}
              />

              <ConfirmDialog
                open={deleteOpen}
                title="Delete Container"
                message={`Delete "${container.name}"? All connections will be removed.`}
                onConfirm={handleDelete}
                onCancel={() => setDeleteOpen(false)}
              />

              {/* <-- ADDED CONFIG DIALOG MOUNT HERE --> */}
              <ContainerConfigDialog
                open={configOpen}
                onClose={() => setConfigOpen(false)}
                container={container}
                onSave={handleConfigSave}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}