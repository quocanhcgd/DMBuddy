import { useEffect, useRef } from 'react';
import { api } from '../api/client';

interface K3WebRtcViewerProps {
  printerId: number;
  className?: string;
  onReady?: () => void;
  onError?: (reason?: string) => void;
}

function decodeAnswer(encoded: string): RTCSessionDescriptionInit {
  const binary = atob(encoded.trim());
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes)) as RTCSessionDescriptionInit;
}

function encodeOffer(offer: RTCSessionDescription): string {
  const bytes = new TextEncoder().encode(JSON.stringify({ type: offer.type, sdp: offer.sdp }));
  let binary = '';
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary);
}

/** Native browser player for Creality K3's local WebRTC signaling service. */
export function K3WebRtcViewer({ printerId, className, onReady, onError }: K3WebRtcViewerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const onReadyRef = useRef(onReady);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onReadyRef.current = onReady;
    onErrorRef.current = onError;
  }, [onError, onReady]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    let disposed = false;
    let peer: RTCPeerConnection | null = null;
    let attempt = 0;
    let fallbackTimeout: number | undefined;
    let failureReason = 'K3 camera did not provide video within 20 seconds';
    const playTimeout = window.setTimeout(() => {
      if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) fail(failureReason);
    }, 20000);
    const fail = (reason: string) => {
      if (!disposed) onErrorRef.current?.(reason);
    };
    const handlePlaying = () => {
      window.clearTimeout(playTimeout);
      if (fallbackTimeout !== undefined) window.clearTimeout(fallbackTimeout);
      onReadyRef.current?.();
    };
    video.addEventListener('playing', handlePlaying);

    const connect = async (direction: 'recvonly' | 'sendrecv') => {
      attempt += 1;
      const currentAttempt = attempt;
      if (fallbackTimeout !== undefined) window.clearTimeout(fallbackTimeout);
      peer?.close();
      peer = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
      });
      const currentPeer = peer;
      const handleTrack = (event: RTCTrackEvent) => {
        if (disposed || currentAttempt !== attempt) return;
        video.srcObject = event.streams[0] || new MediaStream([event.track]);
        void video.play().catch(() => undefined);
      };
      const handleConnectionState = () => {
        if (disposed || currentAttempt !== attempt) return;
        if (currentPeer.connectionState === 'failed') {
          failureReason = 'K3 WebRTC ICE connection failed; check that this browser can reach the printer on the LAN';
        }
        if (currentPeer.connectionState !== 'failed') return;
        if (direction === 'recvonly') void connect('sendrecv');
        else fail(failureReason);
      };
      currentPeer.addEventListener('track', handleTrack);
      currentPeer.addEventListener('connectionstatechange', handleConnectionState);

      try {
        currentPeer.addTransceiver('video', { direction });
        const offer = await currentPeer.createOffer();
        await currentPeer.setLocalDescription(offer);
        if (currentPeer.iceGatheringState !== 'complete') {
          await new Promise<void>((resolve) => {
            const timeout = window.setTimeout(resolve, 5000);
            const check = () => {
              if (currentPeer.iceGatheringState === 'complete') {
                window.clearTimeout(timeout);
                currentPeer.removeEventListener('icegatheringstatechange', check);
                resolve();
              }
            };
            currentPeer.addEventListener('icegatheringstatechange', check);
          });
        }
        if (disposed || currentAttempt !== attempt || !currentPeer.localDescription) return;
        const response = await api.postK3WebRtcOffer(printerId, encodeOffer(currentPeer.localDescription));
        await currentPeer.setRemoteDescription(decodeAnswer(response.answer));
        failureReason = 'K3 signaling answered, but WebRTC media did not arrive; check LAN routing and ICE connectivity';
        fallbackTimeout = window.setTimeout(() => {
          if (disposed || currentAttempt !== attempt || video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) return;
          if (direction === 'recvonly') void connect('sendrecv');
          else fail(failureReason);
        }, 8000);
      } catch (error) {
        if (!disposed && currentAttempt === attempt) {
          console.warn('K3 WebRTC connection failed', error);
          failureReason = error instanceof Error ? `K3 signaling failed: ${error.message}` : 'K3 signaling failed';
          if (direction === 'recvonly') void connect('sendrecv');
          else fail(failureReason);
        }
      }
    };

    void connect('recvonly');
    return () => {
      disposed = true;
      window.clearTimeout(playTimeout);
      if (fallbackTimeout !== undefined) window.clearTimeout(fallbackTimeout);
      video.removeEventListener('playing', handlePlaying);
      peer?.close();
      video.srcObject = null;
    };
  }, [printerId]);

  return (
    <video
      ref={videoRef}
      autoPlay
      muted
      playsInline
      className={className}
      aria-label="Camera stream"
    />
  );
}
