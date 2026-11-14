/** The e-Class server remembers one active course per login session. */
export class LmsAccess {
  private tail: Promise<void> = Promise.resolve();
  browserCourse: string | undefined;

  async acquire(): Promise<() => void> {
    const previous = this.tail;
    let release!: () => void;
    this.tail = new Promise<void>((resolve) => { release = resolve; });
    await previous;
    return release;
  }

  async connectorRead<T>(read: () => Promise<T>, mayStart?: () => boolean): Promise<T> {
    const release = await this.acquire();
    try {
      if (mayStart && !mayStart()) throw new BackgroundReadDeferred();
      this.browserCourse = undefined;
      return await read();
    } finally {
      release();
    }
  }
}

export class BackgroundReadDeferred extends Error {}
