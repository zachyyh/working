import React, { useState } from 'react';
import { Dialog } from '../ui/Dialog';
import type { Container } from '../../data/sampleTopology';

interface ContainerConfigDialogProps {
  open: boolean;
  onClose: () => void;
  container: Container | null;
  onSave: (config: Record<string, any>) => void;
}

function ContainerConfigDialogInner({ onClose, container, onSave }: Omit<ContainerConfigDialogProps, 'open'>) {
  // Initialize state directly from the container config
  const [localConfig, setLocalConfig] = useState<Record<string, any>>(container?.config || {});

  if (!container) return null;

  const handleChange = (key: string, value: any) => {
    // 1. Update the local text box immediately
    const updatedConfig = { ...localConfig, [key]: value };
    setLocalConfig(updatedConfig);
    
    // 2. Autosave it to NodeInfoPanel in the background
    onSave(updatedConfig); 
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(localConfig);
    onClose();
  };

  // Shared styles to match your FormField and SelectField aesthetics
  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontFamily: "var(--font-mono)",
    fontSize: '13px',
    color: 'var(--text-dim)',
    textTransform: 'uppercase',
    letterSpacing: '1px',
    marginBottom: '6px',
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    boxSizing: 'border-box',
    padding: '8px 12px',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border-color)',
    borderRadius: '4px',
    color: 'var(--text-primary)',
    fontFamily: "var(--font-mono)",
    fontSize: '15px',
    outline: 'none',
  };

  return (
    <form onSubmit={handleSubmit}>

{/* ── WEB SERVER CONFIGURATION ── */}
      {container.type === 'web-server' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
            <div>
              <label style={labelStyle}>Domain Name</label>
              <input 
                value={localConfig.domain_name || ''} 
                onChange={(e) => handleChange('domain_name', e.target.value)}
                placeholder="e.g., example.com"
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>Listening Port</label>
              <input 
                value={localConfig.nginx_port || ''} 
                onChange={(e) => handleChange('nginx_port', e.target.value)}
                placeholder="80"
                style={inputStyle}
              />
            </div>
          </div>
          
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Directory Browsing (Autoindex)</label>
            <select 
              value={localConfig.nginx_autoindex || 'off'} 
              onChange={(e) => handleChange('nginx_autoindex', e.target.value)}
              style={inputStyle}
            >
              <option value="off">Off (Secure)</option>
              <option value="on">On (Allows listing files)</option>
            </select>
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Custom index.html Content</label>
            <textarea 
              value={localConfig.index_html || ''} 
              onChange={(e) => handleChange('index_html', e.target.value)}
              placeholder="<h1>Welcome to the web server!</h1>"
              style={{ ...inputStyle, height: '140px', resize: 'vertical' }}
            />
          </div>
        </>
      )}

      {/* ── DIRECTORY SERVER CONFIGURATION ── */}
      {container.type === 'directory-server' && (
        <>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>LDAP Domain (Base DN)</label>
            <input 
              value={localConfig.ldap_domain || ''} 
              onChange={(e) => handleChange('ldap_domain', e.target.value)}
              placeholder="dc=ae3gis,dc=local"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Admin Password</label>
            <input 
              value={localConfig.ldap_admin_pw || ''} 
              onChange={(e) => handleChange('ldap_admin_pw', e.target.value)}
              placeholder="admin"
              type="password"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Groups (Comma-separated)</label>
            <textarea 
              value={localConfig.ldap_groups || ''} 
              onChange={(e) => handleChange('ldap_groups', e.target.value)}
              placeholder="admins, students, faculty"
              style={{ ...inputStyle, height: '60px', resize: 'vertical' }}
            />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Users (Comma-separated)</label>
            <textarea 
              value={localConfig.ldap_users || ''} 
              onChange={(e) => handleChange('ldap_users', e.target.value)}
              placeholder="jsmith, mdoe, bwayne"
              style={{ ...inputStyle, height: '80px', resize: 'vertical' }}
            />
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              Note: Default user password is 'password123'
            </span>
          </div>
        </>
      )}

      {/* ── FILE SERVER (SAMBA) CONFIGURATION ── */}
      {container.type === 'file-server' && (
        <>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Share Name</label>
            <input 
              value={localConfig.samba_share_name || ''} 
              onChange={(e) => handleChange('samba_share_name', e.target.value)}
              placeholder="public"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Directory Path</label>
            <input 
              value={localConfig.samba_share_path || ''} 
              onChange={(e) => handleChange('samba_share_path', e.target.value)}
              placeholder="/srv/samba/public"
              style={inputStyle}
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
            <div>
              <label style={labelStyle}>Guest Access</label>
              <select 
                value={localConfig.samba_guest_ok || 'yes'} 
                onChange={(e) => handleChange('samba_guest_ok', e.target.value)}
                style={inputStyle}
              >
                <option value="yes">Yes (Anonymous allowed)</option>
                <option value="no">No (Auth required)</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>Read Only</label>
              <select 
                value={localConfig.samba_read_only || 'no'} 
                onChange={(e) => handleChange('samba_read_only', e.target.value)}
                style={inputStyle}
              >
                <option value="no">No (Read/Write)</option>
                <option value="yes">Yes (Read Only)</option>
              </select>
            </div>
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Authenticated Users (Comma-separated)</label>
            <textarea 
              value={localConfig.samba_users || ''} 
              onChange={(e) => handleChange('samba_users', e.target.value)}
              placeholder="jsmith, mdoe"
              style={{ ...inputStyle, height: '60px', resize: 'vertical' }}
            />
            <span style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              Note: Default user password is 'password123'
            </span>
          </div>
        </>
      )}

      {/* ── HONEYPOT (OPENCANARY) CONFIGURATION ── */}
      {container.type === 'honeypot' && (
        <>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Honeypot Modules (Detectors)</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              
              <div>
                <label style={{...labelStyle, fontSize: '11px'}}>FTP (Port 21)</label>
                <select value={localConfig.oc_ftp || 'true'} onChange={(e) => handleChange('oc_ftp', e.target.value)} style={inputStyle}>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              </div>

              <div>
                <label style={{...labelStyle, fontSize: '11px'}}>HTTP (Port 80)</label>
                <select value={localConfig.oc_http || 'true'} onChange={(e) => handleChange('oc_http', e.target.value)} style={inputStyle}>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              </div>

              <div>
                <label style={{...labelStyle, fontSize: '11px'}}>SSH (Port 22)</label>
                <select value={localConfig.oc_ssh || 'true'} onChange={(e) => handleChange('oc_ssh', e.target.value)} style={inputStyle}>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              </div>

              <div>
                <label style={{...labelStyle, fontSize: '11px'}}>Telnet (Port 23)</label>
                <select value={localConfig.oc_telnet || 'true'} onChange={(e) => handleChange('oc_telnet', e.target.value)} style={inputStyle}>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              </div>

              <div>
                <label style={{...labelStyle, fontSize: '11px'}}>SMB (Port 445)</label>
                <select value={localConfig.oc_smb || 'true'} onChange={(e) => handleChange('oc_smb', e.target.value)} style={inputStyle}>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              </div>

            </div>
          </div>
        </>
      )}

      {/* ── DATABASE SERVER (POSTGRESQL) CONFIGURATION ── */}
      {container.type === 'database-server' && (
        <>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Database Name</label>
            <input 
              value={localConfig.pg_db_name || ''} 
              onChange={(e) => handleChange('pg_db_name', e.target.value)}
              placeholder="webapp_db"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Database Username</label>
            <input 
              value={localConfig.pg_user || ''} 
              onChange={(e) => handleChange('pg_user', e.target.value)}
              placeholder="dbadmin"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Database Password</label>
            <input 
              value={localConfig.pg_pass || ''} 
              onChange={(e) => handleChange('pg_pass', e.target.value)}
              placeholder="password123"
              type="password"
              style={inputStyle}
            />
          </div>
        </>
      )}

      {/* ── PROXY SERVER (SQUID) CONFIGURATION ── */}
      {container.type === 'proxy' && (
        <>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Allowed Client Subnets (Comma-separated)</label>
            <input 
              value={localConfig.squid_allowed_subnets || ''} 
              onChange={(e) => handleChange('squid_allowed_subnets', e.target.value)}
              placeholder="e.g., 10.0.0.0/24, 192.168.1.0/24 (Leave blank for all)"
              style={inputStyle}
            />
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Blocked Domains (Comma-separated or Newlines)</label>
            <textarea 
              value={localConfig.squid_blocked_domains || ''} 
              onChange={(e) => handleChange('squid_blocked_domains', e.target.value)}
              placeholder="casino.com, malware.local"
              style={{ ...inputStyle, height: '80px', resize: 'vertical' }}
            />
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>Proxy Authentication (Optional)</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <input 
                value={localConfig.squid_auth_user || ''} 
                onChange={(e) => handleChange('squid_auth_user', e.target.value)}
                placeholder="Username"
                style={{ ...inputStyle, fontSize: '14px' }}
              />
              <input 
                value={localConfig.squid_auth_pass || ''} 
                onChange={(e) => handleChange('squid_auth_pass', e.target.value)}
                placeholder="Password"
                type="password"
                style={{ ...inputStyle, fontSize: '14px' }}
              />
            </div>
          </div>
        </>
      )}

      {/* ── FALLBACK FOR UNCONFIGURED TYPES ── */}
      {container.type !== 'firewall' && 
       container.type !== 'web-server' && 
       container.type !== 'directory-server' && 
       container.type !== 'file-server' && 
       container.type !== 'honeypot' && 
       container.type !== 'database-server' &&
       container.type !== 'proxy' && (  
        <div style={{ 
          color: 'var(--text-dim)', 
          marginBottom: '16px',
          fontFamily: 'var(--font-mono)',
          fontSize: '13px',
          padding: '16px',
          border: '1px dashed var(--border-color)',
          borderRadius: '4px',
          textAlign: 'center'
        }}>
          No custom configurations available for {container.type} nodes yet.
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '24px' }}>
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
            background: 'rgba(255, 193, 7, 0.08)',
            border: '1px solid var(--neon-yellow, #ffc107)',
            borderRadius: '4px',
            color: 'var(--neon-yellow, #ffc107)',
            fontFamily: "var(--font-mono)",
            fontSize: '15px',
            cursor: 'pointer',
          }}
        >
          Save Configuration
        </button>
      </div>
    </form>
  );
}

// Wrapper component to utilize the global <Dialog> overlay system
export function ContainerConfigDialog({ open, onClose, container, onSave }: ContainerConfigDialogProps) {
  return (
    <Dialog 
      title={`Configure ${container?.name || 'Node'}`} 
      open={open} 
      onClose={onClose} 
      width={460}
    >
      {open && <ContainerConfigDialogInner onClose={onClose} container={container} onSave={onSave} />}
    </Dialog>
  );
}