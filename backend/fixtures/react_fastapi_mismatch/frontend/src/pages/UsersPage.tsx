import { useEffect, useState } from "react";

import { getUser, listUsers } from "../api/users";
import type { User } from "../api/client";

export function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [selected, setSelected] = useState<User | null>(null);

  useEffect(() => {
    listUsers().then(setUsers).catch(console.error);
  }, []);

  function onSelect(id: number) {
    getUser(id).then(setSelected).catch(console.error);
  }

  return (
    <div>
      <h1>Users</h1>
      <ul>
        {users.map((user) => (
          <li key={user.id} onClick={() => onSelect(user.id)}>
            {user.fullName} ({user.email})
          </li>
        ))}
      </ul>
      {selected && <p>Selected: {selected.fullName}</p>}
    </div>
  );
}
