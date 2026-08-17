import { describe, expect, it } from "vitest";
import { ElkResultNode, resolvePositions } from "./elkPositions";

describe("resolvePositions", () => {
  it("converts a flat node's top-left corner to a centre", () => {
    const root: ElkResultNode = {
      id: "root",
      children: [{ id: "a", x: 10, y: 20, width: 100, height: 40 }],
    };
    expect(resolvePositions(root).get("a")).toEqual({ x: 10 + 50, y: 20 + 20 });
  });

  it("LOADBEARING: a nested node's position accumulates every ancestor's offset", () => {
    // ELK gives each node's x/y relative to its OWN parent's origin, not the
    // canvas -- a child positioned at (5,5) inside a parent at (100,100) sits
    // at canvas (105,105) before centring, not (5,5).
    const root: ElkResultNode = {
      id: "root",
      children: [{
        id: "dir",
        x: 100, y: 100, width: 200, height: 150,
        children: [{ id: "file", x: 5, y: 5, width: 20, height: 10 }],
      }],
    };
    const positions = resolvePositions(root);
    expect(positions.get("file")).toEqual({ x: 100 + 5 + 10, y: 100 + 5 + 5 });
  });

  it("accumulates through three levels of nesting", () => {
    const root: ElkResultNode = {
      id: "root",
      children: [{
        id: "a", x: 10, y: 10, width: 0, height: 0,
        children: [{
          id: "b", x: 20, y: 20, width: 0, height: 0,
          children: [{ id: "c", x: 5, y: 5, width: 4, height: 4 }],
        }],
      }],
    };
    const positions = resolvePositions(root);
    // 10 + 20 + 5 + (4/2) = 37
    expect(positions.get("c")).toEqual({ x: 37, y: 37 });
  });

  it("a node missing x/y/width/height defaults to zero rather than NaN", () => {
    const root: ElkResultNode = { id: "root", children: [{ id: "bare" }] };
    expect(resolvePositions(root).get("bare")).toEqual({ x: 0, y: 0 });
  });

  it("siblings at the same level do not affect each other's position", () => {
    const root: ElkResultNode = {
      id: "root",
      children: [
        { id: "a", x: 0, y: 0, width: 10, height: 10 },
        { id: "b", x: 200, y: 0, width: 10, height: 10 },
      ],
    };
    const positions = resolvePositions(root);
    expect(positions.get("a")).toEqual({ x: 5, y: 5 });
    expect(positions.get("b")).toEqual({ x: 205, y: 5 });
  });

  it("an empty graph resolves to no positions", () => {
    expect(resolvePositions({ id: "root" }).size).toBe(0);
  });

  it("both a compound parent and its children get positions", () => {
    // The caller only APPLIES positions to leaf (file) nodes -- cytoscape
    // auto-fits a compound node's box around its children -- but this
    // function itself resolves every node in the tree, parent included,
    // because a child's offset accumulation depends on the parent's entry
    // being present.
    const root: ElkResultNode = {
      id: "root",
      children: [{
        id: "dir", x: 0, y: 0, width: 50, height: 50,
        children: [{ id: "file", x: 10, y: 10, width: 4, height: 4 }],
      }],
    };
    const positions = resolvePositions(root);
    expect(positions.has("dir")).toBe(true);
    expect(positions.has("file")).toBe(true);
  });
});
