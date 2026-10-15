export interface Product {
  id: number;
  sku: string;
  name: string;
  // Present in the ORM model but never created in the database (MX-DB-001).
  warehouseCode: string | null;
  unitPrice: number;
  reorderLevel: number;
}

export async function listProducts(): Promise<Product[]> {
  const response = await fetch("/api/products");
  return response.json();
}

export async function getLowStock(): Promise<Product[]> {
  const response = await fetch("/api/products/low-stock");
  return response.json();
}
