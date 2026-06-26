db = db.getSiblingDB('nexuschat_db');

db.createUser({
  user: 'nexus',
  pwd: 'nexus123',
  roles: [
    {
      role: 'readWrite',
      db: 'nexuschat_db',
    },
  ],
});

db.createCollection('conversations');

db.conversations.insertOne({
    username: "system",
    query: "Initial document",
    response: "Welcome to Nexus Platform!",
    timestamp: new Date()
});