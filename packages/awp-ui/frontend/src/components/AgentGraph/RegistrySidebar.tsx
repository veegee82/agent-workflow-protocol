import { ToolRegistryPanel } from './ToolRegistryPanel';
import { SkillRegistryPanel } from './SkillRegistryPanel';

/**
 * Floating column docking the Tool and Skill registry panels at the top
 * of the graph canvas. Positioned at ``right-20`` so the FilterToolbar at
 * ``right-4`` stays visible next to it instead of being obscured.
 */
export function RegistrySidebar() {
  return (
    <div
      className="absolute top-3 right-20 z-20 flex flex-col gap-2 w-72 pointer-events-auto"
      style={{ maxHeight: 'calc(100% - 1.5rem)' }}
    >
      <ToolRegistryPanel />
      <SkillRegistryPanel />
    </div>
  );
}
