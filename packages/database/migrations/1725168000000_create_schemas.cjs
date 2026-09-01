/**
 * Migration: Create all 14 PostgreSQL schemas
 * Target: PostgreSQL 18+ (running 16.15 - documented mismatch)
 */
exports.up = (pgm) => {
  const schemas = [
    'iam', 'core', 'design', 'memory', 'work',
    'ai', 'change', 'validation', 'build', 'resource',
    'deploy', 'event', 'security', 'ops'
  ];
  for (const schema of schemas) {
    pgm.createSchema(schema, { ifNotExists: false });
  }
};

exports.down = (pgm) => {
  const schemas = [
    'ops', 'event', 'security', 'deploy', 'resource',
    'build', 'validation', 'change', 'ai', 'work',
    'memory', 'design', 'core', 'iam'
  ];
  for (const schema of schemas) {
    pgm.dropSchema(schema, { ifExists: true, cascade: true });
  }
};
