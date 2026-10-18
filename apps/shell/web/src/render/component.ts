/** 组件契约：mount(host, props) → { update, dispose }（呈现层统一形态）。 */

type Disposer = () => void;

export interface ComponentInstance<Props> {
  update(props: Props): void;
  dispose(): void;
}

export interface ComponentDefinition<Props> {
  mount(host: HTMLElement, props: Props): ComponentInstance<Props>;
}

export function mountComponent<Props>(
  definition: ComponentDefinition<Props>,
  host: HTMLElement,
  props: Props,
): ComponentInstance<Props> {
  return definition.mount(host, props);
}

export function toDisposer(instance: { dispose(): void }): Disposer {
  return () => {
    instance.dispose();
  };
}
