/**
 * Hero background. Falls back to the CSS aurora (three blurred, drifting
 * blobs) until a real video or image asset is supplied via props.
 */
export default function HeroMedia({ videoSrc, imageSrc }: { videoSrc?: string; imageSrc?: string }) {
  return (
    <div className="media">
      {videoSrc ? (
        <video className="absolute inset-0 w-full h-full object-cover" autoPlay muted loop playsInline src={videoSrc} />
      ) : imageSrc ? (
        <img className="absolute inset-0 w-full h-full object-cover" src={imageSrc} alt="" />
      ) : (
        <div className="aurora">
          <i />
          <i />
          <i />
        </div>
      )}
      <div className="dots" />
      <div className="scrim" />
    </div>
  );
}
