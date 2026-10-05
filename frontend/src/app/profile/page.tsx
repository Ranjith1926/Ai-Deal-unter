import type { Metadata } from "next";
import { LogoutButton } from "@/components/LogoutButton";
import { ChannelTests, PasswordForm, ProfileForm } from "@/components/ProfileForms";
import { tryApi } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { requireUser } from "@/lib/session";
import type { NotificationChannels } from "@/lib/types";

export const metadata: Metadata = { title: "Your profile", robots: { index: false } };

export default async function ProfilePage() {
  const user = await requireUser("/profile");
  const available = (await tryApi<NotificationChannels>("/api/notifications/channels", { revalidate: 60 }))?.data ?? null;
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold md:text-4xl">Your profile</h1>
          <p className="mt-1 text-muted">Member since {formatDate(user.created_at, { month: "long", year: "numeric" })}</p>
        </div>
        <LogoutButton className="btn btn-outline btn-sm" />
      </div>
      <section aria-labelledby="acct" className="card p-5 md:p-6">
        <h2 id="acct" className="mb-4 text-xl font-bold">Account &amp; notifications</h2>
        <ProfileForm user={user} available={available} />
      </section>
      <section aria-labelledby="tests" className="card p-5 md:p-6">
        <h2 id="tests" className="mb-4 text-xl font-bold">Test your notifications</h2>
        <ChannelTests user={user} available={available} />
      </section>
      <section aria-labelledby="sec" className="card p-5 md:p-6">
        <h2 id="sec" className="mb-4 text-xl font-bold">Password</h2>
        <PasswordForm />
      </section>
    </div>
  );
}
