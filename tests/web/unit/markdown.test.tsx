import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Markdown } from "../../../web/src/chat/markdown";

it("negrito vira <strong>, e o asterisco some", () => {
  const { container } = render(<Markdown texto="Quero o **Completo** mesmo" />);
  expect(container.querySelector("strong")).toHaveTextContent("Completo");
  expect(container.textContent).not.toContain("*");
});

it("lista com hífen vira <ul>", () => {
  const { container } = render(
    <Markdown texto={"Os planos:\n- Essencial: colisão\n- Completo: + vidros"} />,
  );
  expect(container.querySelectorAll("ul li")).toHaveLength(2);
  expect(container.textContent).not.toContain("- Essencial");
});

it("lista numerada vira <ol>", () => {
  const { container } = render(
    <Markdown texto={"Faltam duas:\n1. A data\n2. O plano"} />,
  );
  expect(container.querySelectorAll("ol li")).toHaveLength(2);
});

it("o caso real do agente: parágrafo, lista e negrito juntos", () => {
  const { container } = render(
    <Markdown
      texto={
        "CEP registrado!\n\nFaltam só duas coisas:\n\n1. Quando começa?\n2. Qual plano?\n\n" +
        "- **Essencial**: colisão, roubo e furto\n- **Completo**: tudo do Essencial + vidros"
      }
    />,
  );
  expect(container.querySelectorAll("ol li")).toHaveLength(2);
  expect(container.querySelectorAll("ul li")).toHaveLength(2);
  expect(container.querySelectorAll("strong")).toHaveLength(2);
  expect(container.textContent).not.toContain("**");
});

it("quebra simples vira <br>, quebra dupla separa parágrafos", () => {
  const { container } = render(<Markdown texto={"uma\ndois\n\ntrês"} />);
  expect(container.querySelectorAll("p")).toHaveLength(2);
  expect(container.querySelectorAll("br")).toHaveLength(1);
});

it("NÃO renderiza HTML — texto do lead e do modelo são não confiáveis", () => {
  const { container } = render(
    <Markdown texto={'<img src=x onerror="alert(1)"> <b>a</b> <script>x</script>'} />,
  );
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("b")).toBeNull();
  // sai como texto, que é feio e é o comportamento certo
  expect(container.textContent).toContain("<img");
});

it("NÃO renderiza link — superfície que ninguém pediu numa tela pública", () => {
  const { container } = render(
    <Markdown texto="veja [aqui](javascript:alert(1))" />,
  );
  expect(container.querySelector("a")).toBeNull();
});

it("texto sem marcação nenhuma sai igual", () => {
  render(<Markdown texto="Oi! Tudo bem?" />);
  expect(screen.getByText("Oi! Tudo bem?")).toBeVisible();
});

it("asterisco solto não quebra a renderização", () => {
  const { container } = render(<Markdown texto="custa 2 * 3 reais" />);
  expect(container.textContent).toBe("custa 2 * 3 reais");
});
