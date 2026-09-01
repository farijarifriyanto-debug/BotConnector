/**
 * Migration: IAM schema tables
 * iam.users - User identity and authentication metadata
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'iam', name: 'users' },
    {
      id: { type: 'text', primaryKey: true },
      email: { type: 'text', notNull: true, unique: true },
      display_name: { type: 'text', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'iam', name: 'users' });
};
