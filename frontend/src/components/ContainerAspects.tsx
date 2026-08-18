
export type ContainerType =
  | 'database-server'
  | 'web-server'
  | 'directory-server'
  | 'file-server'
  | 'internal-dns-server'
  | 'external-dns-server'
  | 'dhcp-server'
  | 'siem'
  | 'router'
  | 'switch'
  | 'ids'
  | 'bastion'
  | 'honeypot'
  | 'proxy'
  | 'pcap'
  | 'firewall'
  | 'hmi'
  | 'workstation'
  | 'plc';

export const typeOptions = [
  { value: 'database-server', label: 'Database Server' },  { value: 'web-server', label: 'Web Server' },  { value: 'directory-server', label: 'Directory Server' },  { value: 'file-server', label: 'File Server' },  { value: 'internal-dns-server', label: 'Internal-dns Server' },  { value: 'external-dns-server', label: 'External-dns Server' },  { value: 'dhcp-server', label: 'Dhcp Server' },  { value: 'siem', label: 'siem' },  { value: 'router', label: 'router' },  { value: 'switch', label: 'switch' },  { value: 'ids', label: 'ids' },  { value: 'bastion', label: 'bastion' },  { value: 'honeypot', label: 'honeypot' },  { value: 'proxy', label: 'proxy' },  { value: 'pcap', label: 'pcap' },  { value: 'firewall', label: 'firewall' },  { value: 'hmi', label: 'hmi' },  { value: 'workstation', label: 'workstation' },  { value: 'plc', label: 'plc' }
];

export const typeColors: Record<ContainerType, string> = {
  'database-server': '#240177',  'web-server': '#00ff9f',  'directory-server': '#240177',  'file-server': '#00d4ff',  'internal-dns-server': '#240177',  'external-dns-server': '#240177',  'dhcp-server': '#240177',  'siem': '#240177',  'router': '#ff00ff',  'switch': '#ffaa00',  'ids': '#240177',  'bastion': '#240177',  'honeypot': '#240177',  'proxy': '#240177',  'pcap': '#240177',  'firewall': '#ff3344',  'hmi': '#33ccff',  'workstation': '#4466ff',  'plc': '#ffaa00'
};

export const typeLabels: Record<ContainerType, string> = {
  'database-server': 'DB',  'web-server': 'WEB',  'directory-server': 'DIR',  'file-server': 'FS',  'internal-dns-server': 'IDNS',  'external-dns-server': 'EDNS',  'dhcp-server': 'DHCP',  'siem': 'SIEM',  'router': 'RTR',  'switch': 'SW',  'ids': 'IDS',  'bastion': 'BS',  'honeypot': 'HP',  'proxy': 'PXY',  'pcap': 'PCAP',  'firewall': 'FW',  'hmi': 'HMI',  'workstation': 'WS',  'plc': 'PLC'
};

export const typeDisplayNames: Record<string, string> = {
  'database-server': 'Database Server',  'web-server': 'Web Server',  'directory-server': 'Directory Server',  'file-server': 'File Server',  'internal-dns-server': 'Internal-dns Server',  'external-dns-server': 'External-dns Server',  'dhcp-server': 'Dhcp Server',  'siem': 'siem',  'router': 'router',  'switch': 'switch',  'ids': 'ids',  'bastion': 'bastion',  'honeypot': 'honeypot',  'proxy': 'proxy',  'pcap': 'pcap',  'firewall': 'firewall',  'hmi': 'hmi',  'workstation': 'workstation',  'plc': 'plc'
};

export const menuHierarchy: Record<string, Partial<Record<ContainerType, string[]>>> = {
  "server": {
    "database-server": [
      "postgres 1.0",
      "postgres latest"
    ],
    "web-server": [
      "nginx 1.0",
      "nginx latest"
    ],
    "directory-server": [
      "openldap latest"
    ],
    "file-server": [
      "samba latest"
    ],
    "internal-dns-server": [
      "bind9 latest"
    ],
    "external-dns-server": [
      "bind9 latest"
    ],
    "dhcp-server": [
      "isc-dhcp latest"
    ]
  },
  "management": {
    "siem": [
      "wazuh 1.0",
      "wazuh latest"
    ],
    "router": [
      "frrouting latest"
    ],
    "switch": [
      "open-vswitch latest"
    ],
    "ids": [
      "suricata-snort latest"
    ],
    "bastion": [
      "ssh latest"
    ],
    "honeypot": [
      "opencanary latest"
    ],
    "proxy": [
      "squid-egress latest"
    ],
    "pcap": [
      "tcp latest"
    ],
    "firewall": [
      "vyos latest"
    ],
    "hmi": [
      "alpine+scripts latest"
    ]
  },
  "other": {
    "workstation": [
      "ubuntu latest"
    ],
    "plc": [
      "alpine+scripts latest"
    ]
  }
};
