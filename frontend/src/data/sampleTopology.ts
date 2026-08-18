// ── Types ──────────────────────────────────────────────────────────
import type { ContainerType } from '../components/ContainerAspects';

export interface Container {
  id: string;
  name: string;
  type: ContainerType;
  ip: string;
  kind?: string;
  image?: string;
  status?: 'running' | 'stopped' | 'paused';
  config?: Record<string, any>;
  metadata?: Record<string, string>;
  persistencePaths?: string[];
}

export interface Connection {
  from: string;
  to: string;
  label?: string;
  fromInterface?: string;
  toInterface?: string;
  fromContainer?: string;
  toContainer?: string;
}

export interface Subnet {
  id: string;
  name: string;
  cidr: string;
  gateway?: string;
  containers: Container[];
  connections: Connection[];
}

export interface Site {
  id: string;
  name: string;
  location: string;
  position: { x: number; y: number };
  subnets: Subnet[];
  subnetConnections: Connection[];
}

export interface ScriptExecution {
  containerId: string;
  script: string;
  args?: string[];
}

export interface AttackPhase {
  id: string;
  name: string;
  description?: string;
  executions: ScriptExecution[];
}

export interface Scenario {
  id: string;
  name: string;
  description?: string;
  phases: AttackPhase[];
}

export interface TopologyData {
  name?: string;
  sites: Site[];
  siteConnections: Connection[];
  scenarios?: Scenario[];
}

// ── Data (loaded from JSON) ───────────────────────────────────────

import topologyJson from './topology.json';

export const sampleTopology: TopologyData = topologyJson.topology as TopologyData;