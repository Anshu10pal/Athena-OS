import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Geometric holographic core (reference-style): a glowing wireframe icosahedron
 * with vertex nodes, concentric ground "portal" rings, a bright energy center,
 * and a vertical light beam. Camera does subtle mouse parallax.
 * `dim` fades the whole core to translucent (used in Chat once a conversation starts).
 */
export default function GeoCore({
  mouse,
  dim = false,
}: {
  mouse: React.MutableRefObject<{ x: number; y: number }>;
  dim?: boolean;
}) {
  const mountRef = useRef<HTMLDivElement>(null);
  const dimRef = useRef(dim);
  dimRef.current = dim;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
    } catch {
      return;
    }
    const W = mount.clientWidth, H = mount.clientHeight;
    renderer.setSize(W, H);
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.cssText = "position:absolute;inset:0;width:100%;height:100%";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, W / H, 0.1, 1000);
    camera.position.set(0, 0, 46);

    const CYAN = new THREE.Color("#5FD3E0");
    const VIOLET = new THREE.Color("#8B7FD6");
    const BRASS = new THREE.Color("#D4B36A");

    // soft sprite for points/glow
    const sc = document.createElement("canvas");
    sc.width = sc.height = 64;
    const sx = sc.getContext("2d")!;
    const sg = sx.createRadialGradient(32, 32, 0, 32, 32, 32);
    sg.addColorStop(0, "rgba(255,255,255,1)");
    sg.addColorStop(0.4, "rgba(255,255,255,0.5)");
    sg.addColorStop(1, "rgba(255,255,255,0)");
    sx.fillStyle = sg;
    sx.fillRect(0, 0, 64, 64);
    const sprite = new THREE.CanvasTexture(sc);

    const core = new THREE.Group();
    scene.add(core);

    // --- wireframe icosahedron shells ---
    const ico1 = new THREE.IcosahedronGeometry(11, 1);
    const shell1 = new THREE.LineSegments(
      new THREE.WireframeGeometry(ico1),
      new THREE.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending })
    );
    core.add(shell1);
    const ico2 = new THREE.IcosahedronGeometry(8.4, 1);
    const shell2 = new THREE.LineSegments(
      new THREE.WireframeGeometry(ico2),
      new THREE.LineBasicMaterial({ color: VIOLET, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending })
    );
    core.add(shell2);

    // --- vertex node points on the outer shell ---
    const vpos = ico1.attributes.position;
    const nodeGeo = new THREE.BufferGeometry();
    nodeGeo.setAttribute("position", new THREE.BufferAttribute(vpos.array.slice(), 3));
    const nodes = new THREE.Points(
      nodeGeo,
      new THREE.PointsMaterial({ size: 1.6, map: sprite, color: CYAN, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    core.add(nodes);

    // --- bright energy center + halos ---
    const center = new THREE.Mesh(new THREE.SphereGeometry(2.2, 24, 24), new THREE.MeshBasicMaterial({ color: "#FFF4D6" }));
    core.add(center);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: sprite, color: BRASS, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false }));
    halo.scale.set(20, 20, 1);
    core.add(halo);
    const haloC = new THREE.Sprite(new THREE.SpriteMaterial({ map: sprite, color: CYAN, transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending, depthWrite: false }));
    haloC.scale.set(42, 42, 1);
    core.add(haloC);

    // --- vertical light beam (gradient alpha) ---
    const bc = document.createElement("canvas");
    bc.width = 8; bc.height = 128;
    const bx = bc.getContext("2d")!;
    const bg = bx.createLinearGradient(0, 0, 0, 128);
    bg.addColorStop(0, "rgba(0,0,0,0)");
    bg.addColorStop(0.5, "rgba(255,255,255,1)");
    bg.addColorStop(1, "rgba(0,0,0,0)");
    bx.fillStyle = bg; bx.fillRect(0, 0, 8, 128);
    const beamTex = new THREE.CanvasTexture(bc);
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.35, 0.35, 70, 8, 1, true),
      new THREE.MeshBasicMaterial({ map: beamTex, alphaMap: beamTex, color: CYAN, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide })
    );
    core.add(beam);

    // --- ground portal rings ---
    const rings: THREE.Mesh[] = [];
    for (let i = 0; i < 4; i++) {
      const r = 9 + i * 4.5;
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(r, r + 0.25, 80),
        new THREE.MeshBasicMaterial({ color: i % 2 ? VIOLET : CYAN, transparent: true, opacity: 0.4 - i * 0.06, blending: THREE.AdditiveBlending, side: THREE.DoubleSide })
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = -16;
      core.add(ring);
      rings.push(ring);
    }

    let raf = 0, op = 1;
    const clock = new THREE.Clock();
    const animate = () => {
      const t = clock.getElapsedTime();
      shell1.rotation.y = t * 0.18;
      shell1.rotation.x = t * 0.06;
      nodes.rotation.copy(shell1.rotation);
      shell2.rotation.y = -t * 0.12;
      shell2.rotation.z = t * 0.05;
      const pulse = 1 + Math.sin(t * 2) * 0.08;
      center.scale.setScalar(pulse);
      halo.scale.setScalar(20 * pulse);
      rings.forEach((r, i) => {
        r.rotation.z = t * (0.1 + i * 0.04) * (i % 2 ? -1 : 1);
        const m = r.material as THREE.MeshBasicMaterial;
        m.opacity = (0.4 - i * 0.06) * (0.6 + 0.4 * Math.sin(t * 1.5 - i));
      });

      // smooth dim toward translucent in chat mode
      const target = dimRef.current ? 0.28 : 1;
      op += (target - op) * 0.08;
      core.traverse((o: any) => {
        if (o.material && o.material.opacity !== undefined && o.userData.baseOp === undefined) o.userData.baseOp = o.material.opacity;
      });
      shell1.material.opacity = 0.55 * op;
      shell2.material.opacity = 0.5 * op;
      (nodes.material as THREE.PointsMaterial).opacity = 0.95 * op;
      (halo.material as THREE.SpriteMaterial).opacity = 0.85 * op;
      (haloC.material as THREE.SpriteMaterial).opacity = 0.3 * op;
      (beam.material as THREE.MeshBasicMaterial).opacity = 0.4 * op;

      camera.position.x += (mouse.current.x * 14 - camera.position.x) * 0.04;
      camera.position.y += (-mouse.current.y * 10 - camera.position.y) * 0.04;
      camera.lookAt(0, 0, 0);
      renderer.render(scene, camera);
      raf = requestAnimationFrame(animate);
    };
    animate();

    const onResize = () => {
      const w = mount.clientWidth, h = mount.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      sprite.dispose(); beamTex.dispose();
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={mountRef} style={{ position: "absolute", inset: 0, zIndex: 1 }} aria-hidden="true" />;
}
