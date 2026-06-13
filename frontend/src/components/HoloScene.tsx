import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Three.js WebGL layer: a depth particle starfield + a holographic core
 * (three rotating rings + a glowing sphere). Camera does subtle mouse parallax.
 * Exposes the live mouse target via a ref the DOM layer reads, so cards and
 * the WebGL camera move in sync. Falls back silently if WebGL is unavailable.
 */
export default function HoloScene({ mouse }: { mouse: React.MutableRefObject<{ x: number; y: number }> }) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
    } catch {
      return; // no WebGL — DOM fallback (CSS particles) covers this
    }
    const W = mount.clientWidth;
    const H = mount.clientHeight;
    renderer.setSize(W, H);
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.cssText = "position:absolute;inset:0;width:100%;height:100%";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, W / H, 0.1, 1000);
    camera.position.z = 60;

    // --- soft circular sprite texture for points ---
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const cx = c.getContext("2d")!;
    const g = cx.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.4, "rgba(255,255,255,0.5)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    cx.fillStyle = g;
    cx.fillRect(0, 0, 64, 64);
    const sprite = new THREE.CanvasTexture(c);

    // --- particle starfield (brass + cyan, layered depth) ---
    const COUNT = 1400;
    const positions = new Float32Array(COUNT * 3);
    const colors = new Float32Array(COUNT * 3);
    const brass = new THREE.Color("#D4B36A");
    const cyan = new THREE.Color("#5FD3E0");
    for (let i = 0; i < COUNT; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 260;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 190;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 140 - 40;
      const col = Math.random() > 0.5 ? cyan : brass;
      colors[i * 3] = col.r;
      colors[i * 3 + 1] = col.g;
      colors[i * 3 + 2] = col.b;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const pmat = new THREE.PointsMaterial({
      size: 1.1,
      map: sprite,
      vertexColors: true,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const points = new THREE.Points(geo, pmat);
    scene.add(points);

    // --- holographic core ---
    const core = new THREE.Group();
    core.position.y = 16;   // lift up so the welcome text sits below the orb, not on it
    scene.add(core);

    const ringMat = (color: string, op: number) =>
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: op, blending: THREE.AdditiveBlending });
    const r1 = new THREE.Mesh(new THREE.TorusGeometry(11, 0.16, 12, 90), ringMat("#7FE9F0", 0.8));
    const r2 = new THREE.Mesh(new THREE.TorusGeometry(8.5, 0.14, 12, 90), ringMat("#D4B36A", 0.85));
    const r3 = new THREE.Mesh(new THREE.TorusGeometry(6.5, 0.12, 12, 90), ringMat("#FFFFFF", 0.6));
    r1.rotation.x = 1.1;
    r2.rotation.x = 1.1;
    r2.rotation.y = 0.6;
    core.add(r1, r2, r3);

    // glowing center sphere + additive halo sprite
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(4, 32, 32),
      new THREE.MeshBasicMaterial({ color: "#F4E3B8" })
    );
    core.add(sphere);
    const halo = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: sprite, color: "#D4B36A", transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    halo.scale.set(26, 26, 1);
    core.add(halo);
    const haloCyan = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: sprite, color: "#5FD3E0", transparent: true, opacity: 0.28, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    haloCyan.scale.set(46, 46, 1);
    core.add(haloCyan);

    let raf = 0;
    const clock = new THREE.Clock();
    const animate = () => {
      const t = clock.getElapsedTime();
      points.rotation.y = t * 0.02;
      points.rotation.x = Math.sin(t * 0.05) * 0.05;
      r1.rotation.z = t * 0.4;
      r2.rotation.z = -t * 0.3;
      r3.rotation.y = t * 0.5;
      const pulse = 1 + Math.sin(t * 1.9) * 0.06;
      sphere.scale.setScalar(pulse);
      halo.scale.setScalar(26 * pulse);

      // camera parallax toward mouse target
      camera.position.x += (mouse.current.x * 16 - camera.position.x) * 0.04;
      camera.position.y += (-mouse.current.y * 12 - camera.position.y) * 0.04;
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
      geo.dispose();
      pmat.dispose();
      sprite.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={mountRef} style={{ position: "absolute", inset: 0, zIndex: 1 }} aria-hidden="true" />;
}
